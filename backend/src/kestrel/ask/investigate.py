"""The investigation loop: several measurements, each chosen after the last.

Some questions have no single figure that answers them. "Why did fill rate
drop in the West?" needs the rate, the rate before it, and then a
breakdown of where the difference sits -- and the third query only makes
sense once the second has come back.

So the model plans, one step at a time. What it does *not* do is compute:
every figure still comes from `dispatch.run`, which is the same code path
the dashboard uses (C4.3). The model chooses which measurements to take
and what they mean; it never produces a number, and the guard checks its
prose against the union of everything it was shown.
"""

import logging
import sqlite3
from calendar import monthrange
from collections.abc import Iterator
from datetime import date, timedelta

from kestrel.ask import answer as compose_answer
from kestrel.ask import dispatch, guard
from kestrel.ask.catalogue import Catalogue
from kestrel.ask.gemini import LanguageModel, LanguageUnavailable
from kestrel.ask.types import (
    AskIntent,
    AskMetric,
    AskStep,
    AskTurn,
    Investigation,
    MetricResults,
    StepRecord,
)
from kestrel.reference import scope

logger = logging.getLogger(__name__)

# A backstop, not a target. The model ends the loop by saying it is done;
# this stops one that never does.
MAX_STEPS = 6

_SYSTEM = """You are investigating a supply-chain question by taking
measurements. You do not compute anything: you choose which measurement to
take next, and something else runs it and shows you the result.

Each turn, return one step:
- intent: the measurement to take, in the same shape as a dashboard query.
- reasoning: one short sentence saying why this measurement, in plain
  language. It is shown to the user as the investigation runs.
- done: true when you have enough to answer. Return done with no intent.

How to investigate a question about a change ("why did X drop"):
1. Measure X for the period asked about.
2. Measure X for the period before it, so there is something to compare to.
3. Break X down -- by outlet, route, warehouse or category -- to find where
   the change sits.
4. If a related metric would show something, measure it too. A fill rate
   drop may show up in OTIF or excursions on the same routes.
Stop as soon as you can answer. Fewer, well-chosen measurements beat more.

Metrics and the grains each one supports:
- fill_rate: ordered vs delivered quantity. Grains: {fill_rate}.
- otif: on-time and in-full delivery. Grains: {otif}.
- returns: returns and credit note value leakage. Grains: {returns}.
- near_expiry: stock approaching expiry. Grains: {near_expiry}. It is a
  weekly snapshot, not a period: it has no "before", so do not try to
  compare it across periods.
- excursions: cold-chain temperature excursions. Grains: {excursions}.

Rules:
- grain must be one listed for the metric you chose. A grain a metric does
  not have will fail, and you will be told so.
- period is 'latest', FY<yy>Q<n> (e.g. FY27Q1), <yyyy>-<mm> (e.g. 2026-06),
  <yyyy>-W<ww> (e.g. 2026-W24), or <yyyy-mm-dd>..<yyyy-mm-dd>. The fiscal
  year starts in April. Keep the same period across steps unless you are
  deliberately comparing two.
- region_id must come from the regions listed below, or be null.
- q is a substring filter on the breakdown label. Use it to follow a named
  outlet or route you found in an earlier step.
- limit caps the breakdown rows; ascending true puts the worst first.
- Never take the same measurement twice. If you have it, use it.

{coverage}
Regions: {regions}
Warehouses: {warehouses}
Product categories: {categories}
Return reason codes: {reasons}
"""

_CONCLUDE_SYSTEM = """You are explaining what an investigation found, to a
manager reading it in a hurry.

You are given the question and every measurement that was taken. Write at
most four sentences: what the figures show, where the change concentrates,
and what most likely explains it.

Rules:
- Use only numbers that appear verbatim in the measurements above. Never
  compute, round differently, estimate or infer a figure. Changes between
  two periods have already been computed for you where they exist.
- Say where the evidence points, and say plainly when it is thin.
- No greeting, no preamble, no offer to help further.
"""


def headline_rate(result: MetricResults) -> float | None:
    """The one rate a result leads with, whatever shape the metric uses.

    Each metric names its headline differently -- and OTIF's is a row, not
    a number -- so the comparison logic asks here rather than reaching into
    a shape it would have to guess at.
    """
    metric = result.basis.metric
    if metric == "fill_rate":
        return result.headline
    if metric == "otif":
        return result.headline.otif
    if metric == "returns":
        return result.headline.returns_rate
    if metric == "near_expiry":
        return result.headline.near_expiry_rate
    return result.headline.excursion_rate


def _coverage(covered: tuple[str, str] | None) -> str:
    """Tell the model when the data ends, and what "last week" means in it.

    Without this it reads "last week" against today's calendar, finds
    nothing useful, and spends its step budget re-measuring the latest
    quarter -- which is exactly what a live run did.
    """
    if covered is None:
        return "The dataset is empty.\n"
    start, end = covered
    last = date.fromisoformat(end)

    # The week and month the data ends in are usually part-covered, and
    # comparing two days against seven reads as a collapse that is really
    # just a truncated period. The same reason `latest_complete_quarter`
    # excludes the quarter in progress -- applied one grain down.
    week_end = last if last.isoweekday() == 7 else last - timedelta(days=last.isoweekday())
    iso_year, iso_week, _ = week_end.isocalendar()

    month_end = last
    if last.day != monthrange(last.year, last.month)[1]:
        month_end = last.replace(day=1) - timedelta(days=1)

    return (
        f"The data covers {start} to {end} and there is nothing after {end}. "
        f'The last *complete* week is {iso_year}-W{iso_week:02d} and the last '
        f"complete month is {month_end.year}-{month_end.month:02d}; the week "
        f"and month containing {end} are only part-covered, so comparing "
        f'against them is misleading. Read "last week" and "last month" as '
        f"the complete ones, and ask for them directly rather than for "
        f"'latest', which is a whole quarter.\n"
    )


def _comparable(record: StepRecord, intent: AskIntent) -> bool:
    """True when an earlier step measured the same thing over another period.

    Same metric and same scope, different period. A delta across two
    different metrics, or across two different regions, is not a change in
    anything -- it is a subtraction of unrelated numbers.
    """
    return (
        record.result is not None
        and record.intent.metric is intent.metric
        and record.intent.region_id == intent.region_id
        and record.intent.q == intent.q
        and record.intent.period != intent.period
    )


def _delta(
    records: list[StepRecord], intent: AskIntent, result: MetricResults
) -> tuple[float | None, str | None]:
    """The change between this measurement and a comparable earlier one.

    Oriented by time, not by the order the steps were taken. The model
    usually measures the period asked about first and its baseline second,
    so subtracting in step order reports a rise as a fall -- which is
    exactly what a live run did.
    """
    current = headline_rate(result)
    if current is None:
        return None, None

    for other in reversed(records):
        if not _comparable(other, intent):
            continue
        baseline = headline_rate(other.result)
        if baseline is None:
            continue

        this_period = result.basis
        that_period = other.result.basis
        if that_period.period_start <= this_period.period_start:
            earlier, later, rise = that_period, this_period, current - baseline
        else:
            earlier, later, rise = this_period, that_period, baseline - current
        return rise, f"{earlier.period_label} to {later.period_label}"
    return None, None


def _history(
    question: str,
    records: list[StepRecord],
    window: list[AskTurn],
    note: str | None = None,
) -> str:
    """What the model sees before choosing its next step.

    Summaries rather than rows: a breakdown can run to hundreds of rows and
    none of them would change which measurement to take next.
    """
    lines = [f"Question: {question}"]
    if window:
        earlier = "; ".join(turn.question for turn in window)
        lines.append(f"Earlier questions in this conversation: {earlier}")
    if not records:
        lines.append("\nNo measurements taken yet. Take the first one.")
        return "\n".join(lines)

    lines.append("\nMeasurements so far:")
    for number, record in enumerate(records, start=1):
        if record.error:
            lines.append(f"{number}. {record.reasoning}\n   FAILED: {record.error}")
            continue
        change = ""
        if record.delta is not None:
            direction = "up" if record.delta >= 0 else "down"
            change = (
                f"\n   Change from {record.delta_basis}: {direction} "
                f"{abs(record.delta) * 100:.2f} percentage points."
            )
        lines.append(f"{number}. {record.reasoning}\n   {record.summary}{change}")
    if note:
        lines.append(f"\n{note}")
    lines.append("\nTake the next measurement, or set done if you can answer now.")
    return "\n".join(lines)


def _plan(
    client: LanguageModel, catalogue: Catalogue, question: str,
    records: list[StepRecord], window: list[AskTurn],
    covered: tuple[str, str] | None = None, note: str | None = None,
) -> AskStep:
    from kestrel.ask.resolver import _GRAINS  # the one list of legal grains

    system = _SYSTEM.format(
        fill_rate=_GRAINS[AskMetric.FILL_RATE],
        otif=_GRAINS[AskMetric.OTIF],
        returns=_GRAINS[AskMetric.RETURNS],
        near_expiry=_GRAINS[AskMetric.NEAR_EXPIRY],
        excursions=_GRAINS[AskMetric.EXCURSIONS],
        coverage=_coverage(covered),
        regions=", ".join(
            f"{r.region_name} (region_id {r.region_id})" for r in catalogue.regions
        )
        or "none",
        warehouses=", ".join(catalogue.warehouses) or "none",
        categories=", ".join(catalogue.categories) or "none",
        reasons=", ".join(catalogue.return_reasons) or "none",
    )
    try:
        raw = client.generate_json(
            system=system,
            prompt=_history(question, records, window, note),
            schema=AskStep,
        )
    except Exception as exc:
        raise LanguageUnavailable(str(exc)) from exc

    try:
        return AskStep.model_validate(raw)
    except Exception:
        # An unusable step ends the investigation rather than failing it:
        # whatever has already been measured is still a real answer.
        logger.warning("Investigator returned an unusable step", exc_info=True)
        return AskStep(done=True, reasoning="")


def investigate(
    client: LanguageModel,
    conn: sqlite3.Connection,
    question: str,
    catalogue: Catalogue,
    *,
    window: list[AskTurn] | None = None,
    scope_region_id: int | None = None,
    scope_period: str | None = None,
    max_steps: int = MAX_STEPS,
) -> Iterator[StepRecord]:
    """Run the investigation, yielding each measurement as it completes.

    A generator so the endpoint can stream: a six-step investigation is ten
    seconds of silence otherwise, and the steps are worth watching -- they
    are the record of what the answer was actually built from.
    """
    records: list[StepRecord] = []
    window = window or []
    covered = scope.data_range(conn)
    # Intents already measured, so a model that asks twice is answered from
    # what it has. A live run spent three of six steps re-measuring the same
    # quarter; each repeat is a query and a model call bought for nothing.
    seen: set[str] = set()
    note: str | None = None

    for _ in range(max_steps):
        step = _plan(client, catalogue, question, records, window, covered, note)
        note = None
        if step.done or step.intent is None:
            return

        intent = step.intent
        # C5.3: the dashboard's scope fills gaps the question leaves. A
        # region or period named in the question is more specific, so it
        # wins -- the scope never overrides an explicit answer.
        if intent.region_id is None and scope_region_id is not None:
            intent = intent.model_copy(update={"region_id": scope_region_id})
        if intent.period == "latest" and scope_period is not None:
            intent = intent.model_copy(update={"period": scope_period})

        key = intent.model_dump_json()
        if key in seen:
            note = (
                "You have already taken that exact measurement; it is listed "
                "above. Take a different one, or set done if you can answer now."
            )
            continue
        seen.add(key)

        try:
            result = dispatch.run(conn, intent)
        except dispatch.Unanswerable as exc:
            record = StepRecord(
                reasoning=step.reasoning, intent=intent, summary="", error=str(exc)
            )
        except Exception as exc:  # a malformed period, say
            logger.warning("Investigation step failed", exc_info=True)
            record = StepRecord(
                reasoning=step.reasoning, intent=intent, summary="", error=str(exc)
            )
        else:
            change, basis = _delta(records, intent, result)
            record = StepRecord(
                reasoning=step.reasoning,
                intent=intent,
                summary=compose_answer.compose(result, intent.limit),
                result=result,
                delta=change,
                delta_basis=basis,
            )

        records.append(record)
        yield record


def conclude(
    client: LanguageModel, question: str, records: list[StepRecord]
) -> str | None:
    """The model's explanation, or None if it invented a figure.

    The guard runs over every step's result at once, so the model may quote
    anything it was actually shown and nothing else. Its *reasoning* about
    those figures is its own -- that is the point of asking it -- but the
    figures are ours.
    """
    measured = [record for record in records if record.result is not None]
    if not measured:
        return None

    prompt = "\n\n".join(
        [f"Question: {question}"]
        + [
            f"Measurement {number}: {record.reasoning}\n{record.summary}"
            + (
                f"\nChange from {record.delta_basis}: "
                f"{'up' if record.delta >= 0 else 'down'} by "
                f"{abs(record.delta) * 100:.2f} percentage points."
                if record.delta is not None
                else ""
            )
            for number, record in enumerate(measured, start=1)
        ]
    )
    try:
        prose = client.generate_text(system=_CONCLUDE_SYSTEM, prompt=prompt)
    except Exception:
        logger.warning("Could not write the investigation summary", exc_info=True)
        return None
    if not prose:
        return None

    # Everything the model was shown, checked at once -- but only the
    # parts we computed. `reasoning` is the model's own text, and walking
    # it would let a model write a figure into one step's reasoning and
    # quote it as a finding in the next.
    computed = [
        {"summary": record.summary, "result": record.result, "delta": record.delta}
        for record in measured
    ]
    guarded = guard.apply(prose, computed)
    if guarded is None:
        logger.warning("Investigation summary quoted a figure no step produced; dropped")
    return guarded


def run(
    client: LanguageModel,
    conn: sqlite3.Connection,
    question: str,
    catalogue: Catalogue,
    **kwargs: object,
) -> Investigation:
    """The whole investigation, for callers that are not streaming."""
    records = list(investigate(client, conn, question, catalogue, **kwargs))  # type: ignore[arg-type]
    measured = [record for record in records if record.result is not None]
    if not measured:
        return Investigation(steps=records, answer="", declined=True)
    return Investigation(
        steps=records,
        # The answer of record is every measurement stated in full. Each
        # summary already carries its figure, period, scope, unit and
        # exclusions (C4.2), so the investigation inherits that rather than
        # composing a new sentence that would have to restate it.
        answer="\n\n".join(record.summary for record in measured),
        explanation=conclude(client, question, records),
    )
