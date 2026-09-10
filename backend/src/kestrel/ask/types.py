"""The typed contract between the language model and the metric layer.

The model's only job is to turn a question into one of these objects. It
never sees a row, never writes SQL and never produces a figure, so PRD
C4.3 (answers computed by the same implementations that serve the
dashboard) holds by construction rather than by prompt discipline.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from kestrel.metrics.types import (
    ExcursionsResult,
    MetricResult,
    NearExpiryResult,
    OtifResult,
    ReturnsResult,
    Unit,
)


class AskMetric(StrEnum):
    """The five metrics the product can answer for, plus a refusal.

    UNSUPPORTED is a value in the enum rather than an error path: PRD C4.4
    requires declining to be a first-class outcome, so the model expresses
    "I cannot answer this" inside the same schema as every other answer.
    """

    FILL_RATE = "fill_rate"
    OTIF = "otif"
    RETURNS = "returns"
    NEAR_EXPIRY = "near_expiry"
    EXCURSIONS = "excursions"
    UNSUPPORTED = "unsupported"


class AskGrain(StrEnum):
    """The union of every metric's grain.

    Flat rather than per-metric because a flat response schema is what the
    model resolves reliably. Whether a grain is legal for the chosen metric
    is decided in Python (dispatch), not left to the model.
    """

    REGION = "region"
    WAREHOUSE = "warehouse"
    ROUTE = "route"
    OUTLET = "outlet"
    CATEGORY = "category"
    REASON = "reason"
    MONTH = "month"


class AskIntent(BaseModel):
    """A question, resolved into a request the metric layer can serve."""

    metric: AskMetric
    grain: AskGrain | None = None
    # 'latest' or FY<yy>Q<1-4>. Resolved to real dates by fiscal.py, never
    # by the model: fiscal quarters start in April and model date
    # arithmetic gets quarter boundaries wrong.
    period: str = "latest"
    region_id: int | None = None
    unit: Unit = Unit.EACHES
    limit: int | None = Field(default=None, ge=1, le=50)
    ascending: bool = False
    q: str | None = Field(default=None, max_length=200)
    include_excluded: bool = False


class AskTurn(BaseModel):
    """One earlier exchange, as carried back by the client.

    Holds the question and what it resolved to -- never the answer. A
    follow-up like "and Delhi?" needs the previous request to merge onto;
    it does not need the previous figures, and keeping figures out of the
    window means no computed number is ever in the model's context.
    """

    question: str = Field(max_length=500)
    intent: AskIntent


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    # Sliding, overlapping window of recent turns. The server is stateless;
    # the client owns the conversation.
    window: list[AskTurn] = Field(default_factory=list, max_length=10)
    # PRD C5.3: the selected scope applies to ask-anything too. Overrides
    # nothing the question says explicitly -- see resolver.
    region_id: int | None = None


MetricResults = (
    MetricResult | OtifResult | ReturnsResult | NearExpiryResult | ExcursionsResult
)


class AskAnswer(BaseModel):
    """What the endpoint returns.

    `answer` is deterministic and always present when a question was
    answered: it is assembled from the computed result and its basis, so it
    carries the figure, the period, the filters, the unit and the
    exclusions (C4.1, C4.2). `prose` is optional model framing that has
    passed the numeric guard; it is never the source of a figure, and the
    answer reads correctly without it (C4.6). `result` carries the
    supporting figures alongside the prose (C4.5).
    """

    question: str
    intent: AskIntent | None = None
    answer: str
    prose: str | None = None
    result: MetricResults | None = None
    declined: bool = False
    supported_metrics: list[str] | None = None
