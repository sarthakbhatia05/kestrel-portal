"""Question -> AskIntent. The first and only place a model reads a question.

The model's entire output is one AskIntent. It never receives a row, a
figure or a query, so the worst a bad resolution can do is answer a
different question than the one asked -- visibly, because the answer
restates the period, filters and unit it used (PRD C4.2).
"""

import logging

from kestrel.ask.catalogue import Catalogue
from kestrel.ask.gemini import LanguageModel, LanguageUnavailable
from kestrel.ask.types import AskIntent, AskMetric, AskTurn

logger = logging.getLogger(__name__)

SUPPORTED_METRICS = [
    "fill rate (ordered vs delivered, by region, warehouse, route or outlet)",
    "OTIF (on-time in-full delivery, by region, warehouse, route or outlet)",
    "returns and credit note leakage (by category, reason or region)",
    "near-expiry stock (by warehouse or category, as at the latest snapshot)",
    "temperature excursions (by month, route or warehouse)",
]

_GRAINS = {
    AskMetric.FILL_RATE: "region, warehouse, route, outlet",
    AskMetric.OTIF: "region, warehouse, route, outlet",
    AskMetric.RETURNS: "category, reason, region",
    AskMetric.NEAR_EXPIRY: "warehouse, category",
    AskMetric.EXCURSIONS: "month, route, warehouse",
}

_SYSTEM = """You translate a supply-chain question into a structured request.
You do not answer questions and you never produce numbers: something else
computes the figure from the request you return.

Choose exactly one metric:
- fill_rate: ordered vs delivered quantity. Grains: {fill_rate}.
- otif: on-time and in-full delivery performance. Grains: {otif}.
- returns: returns and credit note value leakage. Grains: {returns}.
- near_expiry: stock approaching expiry, as at the latest weekly snapshot.
  Grains: {near_expiry}. It has no period; ignore any period in the question.
- excursions: cold-chain temperature excursions. Grains: {excursions}.
- unsupported: the question is about anything else, including forecasts,
  costs, people, or a metric not in this list. Prefer unsupported over a
  metric that only loosely matches. Answering the wrong question is worse
  than declining.

Also choose a mode:
- lookup: one figure answers the question. "How is OTIF in the West?"
- investigate: the question asks why something changed, where a problem is
  concentrated, or what is driving a number -- anything that needs several
  measurements compared against each other rather than one. "Why did fill
  rate drop in the West last week?" Choose the metric the question is
  about; the investigation decides which measurements to take from there.

Rules:
- grain must be one of the grains listed for the metric you chose.
- period is 'latest' (the most recent complete fiscal quarter) or FY<yy>Q<n>,
  e.g. FY27Q1. The fiscal year starts in April and is named for the year it
  ends in. Use 'latest' whenever the question does not name a quarter.
- region_id must come from the regions listed below. Leave it null when the
  question names no region.
- unit is eaches unless the question asks for cases. It applies to fill rate
  only.
- For "worst N" or "top N", set limit to N; set ascending true for worst,
  best-performing-last questions and false for largest-first questions.
- q is a free-text substring filter on the breakdown label. Use it only for
  an outlet or route named in the question, since those are not listed here.
- include_excluded stays false unless the question explicitly asks to include
  excluded, deleted or test records.
- mode is lookup unless the question needs several measurements compared.

Regions: {regions}
Warehouses: {warehouses}
Product categories: {categories}
Return reason codes: {reasons}
"""


def _system_prompt(catalogue: Catalogue) -> str:
    regions = ", ".join(f"{r.region_name} (region_id {r.region_id})" for r in catalogue.regions)
    return _SYSTEM.format(
        fill_rate=_GRAINS[AskMetric.FILL_RATE],
        otif=_GRAINS[AskMetric.OTIF],
        returns=_GRAINS[AskMetric.RETURNS],
        near_expiry=_GRAINS[AskMetric.NEAR_EXPIRY],
        excursions=_GRAINS[AskMetric.EXCURSIONS],
        regions=regions or "none",
        warehouses=", ".join(catalogue.warehouses) or "none",
        categories=", ".join(catalogue.categories) or "none",
        reasons=", ".join(catalogue.return_reasons) or "none",
    )


def _user_prompt(question: str, window: list[AskTurn]) -> str:
    """The question, preceded by what earlier questions resolved to.

    Earlier answers are deliberately absent: a follow-up like "and Delhi?"
    needs the previous request to build on, not the previous figures, and
    keeping figures out of the prompt means no computed number can be
    reflected back as if the model had produced it.
    """
    if not window:
        return f"Question: {question}"
    history = "\n".join(
        f"- asked: {turn.question}\n  resolved to: {turn.intent.model_dump_json()}"
        for turn in window
    )
    return (
        "Earlier questions in this conversation, and the requests they "
        f"resolved to:\n{history}\n\n"
        "A question that omits a metric, period or region carries the one "
        "from the most recent turn above.\n\n"
        f"Question: {question}"
    )


def resolve(
    client: LanguageModel,
    question: str,
    catalogue: Catalogue,
    window: list[AskTurn] | None = None,
    scope_region_id: int | None = None,
) -> AskIntent:
    """Resolve a question, declining rather than guessing.

    A malformed object or a metric outside the enum resolves to
    `unsupported`: the model answered, and what it produced cannot be
    served. There is no path from a failed resolution to a figure.

    A transport failure raises LanguageUnavailable instead. Reporting an
    outage as "the data cannot answer that" would be a false statement
    about the data, and it is the kind of quiet lie this product exists to
    remove.
    """
    try:
        raw = client.generate_json(
            system=_system_prompt(catalogue),
            prompt=_user_prompt(question, window or []),
            schema=AskIntent,
        )
    except Exception as exc:
        logger.warning("Could not reach the language model", exc_info=True)
        raise LanguageUnavailable(str(exc)) from exc

    try:
        intent = AskIntent.model_validate(raw)
    except Exception:
        logger.warning("Language model returned an unusable intent", exc_info=True)
        return AskIntent(metric=AskMetric.UNSUPPORTED)

    if intent.metric is AskMetric.UNSUPPORTED:
        return AskIntent(metric=AskMetric.UNSUPPORTED)

    # A region_id that is not in the catalogue was invented. Answering with
    # it would silently change the scope of the question, so decline.
    known = {r.region_id for r in catalogue.regions}
    if intent.region_id is not None and intent.region_id not in known:
        logger.warning("Resolver returned unknown region_id %s", intent.region_id)
        return AskIntent(metric=AskMetric.UNSUPPORTED)

    # PRD C5.3: the selected scope applies to every surface. A region named
    # in the question is more specific than the dashboard's selection, so
    # the scope fills a gap rather than overriding an answer.
    if intent.region_id is None and scope_region_id is not None:
        intent = intent.model_copy(update={"region_id": scope_region_id})
    return intent
