from datetime import date

from pydantic import BaseModel


class RuleCount(BaseModel):
    rule_ref: str
    rule_name: str
    count: int


class MeasureExclusions(BaseModel):
    """What one measure leaves out of a scope.

    A row can be removed by several rules at once (a cancelled order at a
    closed outlet), so `by_rule` counts overlap and do not sum to
    `excluded_count`, which counts each row once.
    """

    measure: str
    label: str
    # What a row of this measure is: "order lines", "credit notes", ...
    entity: str
    # False only for near-expiry, which no exclusion rule is scoped to. Its
    # counts are None rather than 0: nothing was checked, so nothing is zero.
    applies: bool
    in_scope_count: int | None
    included_count: int | None
    excluded_count: int | None
    by_rule: list[RuleCount]
    note: str | None = None


class QualityResult(BaseModel):
    period_start: date
    period_end: date
    period_label: str
    scope: str
    measures: list[MeasureExclusions]


class RuleSummary(BaseModel):
    rule_ref: str
    rule_name: str
    kind: str
    applied: str
    recorded: bool
    # Entries in this build's ledger. None when the rule writes no entries,
    # so "not recorded" cannot be misread as "ran and found nothing".
    ledger_count: int | None


class QualityResponse(QualityResult):
    rules: list[RuleSummary]
    # When the curated database was built. The ledger is build-wide, not
    # scoped, so its counts are "as of this build".
    built_at: str | None


class LedgerEntry(BaseModel):
    ledger_id: int
    entity_type: str
    entity_id: str | None
    action: str
    reason: str
    source_system: str | None


class LedgerPage(BaseModel):
    rule_ref: str
    rule_name: str
    total: int
    limit: int
    offset: int
    entries: list[LedgerEntry]
