"""Every normalisation and exclusion rule the PRD defines (6.2, 6.3).

Listed here rather than discovered from the ledger, because the ledger can
only show rules that fired. A rule that was checked and found nothing (N1
and N3 against the real data) and a rule that was never implemented would
otherwise look identical: both simply absent.
"""

import sqlite3
from dataclasses import dataclass

from kestrel.exceptions import AppError
from kestrel.quality.types import LedgerEntry, LedgerPage, RuleSummary


@dataclass(frozen=True)
class Rule:
    ref: str
    name: str
    # "normalisation" repairs a value; "exclusion" removes a row from measures.
    kind: str
    # "build" rules run during the transform; "query" rules run per request,
    # because their outcome depends on the period being viewed.
    applied: str
    # Whether the transform writes a ledger entry each time the rule fires.
    recorded: bool


RULES: tuple[Rule, ...] = (
    Rule("N1", "Case pack fallback to product master", "normalisation", "build", True),
    Rule("N2", "Order timestamps converted to India time", "normalisation", "build", False),
    Rule("N3", "Arrival timestamp unparseable", "normalisation", "build", True),
    Rule("N4", "Return quantity sign-normalised", "normalisation", "build", True),
    Rule("N5", "City name mapped to canonical form", "normalisation", "build", True),
    Rule("N6", "Price resolved as at order date", "normalisation", "build", False),
    Rule("X1", "Soft-deleted outlet excluded", "exclusion", "build", True),
    Rule("X2", "Test or migration outlet excluded", "exclusion", "build", True),
    Rule("X3", "Closed outlet excluded after its closure date", "exclusion", "query", False),
    Rule("X4", "Cancelled or open order excluded", "exclusion", "build", True),
    Rule("X5", "Duplicate outlet resolved to surviving entity", "exclusion", "build", True),
)

RULES_BY_REF: dict[str, Rule] = {rule.ref: rule for rule in RULES}


def catalogue(conn: sqlite3.Connection) -> list[RuleSummary]:
    counts = {
        row[0]: row[1]
        for row in conn.execute("SELECT rule_ref, COUNT(*) FROM quality_ledger GROUP BY rule_ref")
    }
    return [
        RuleSummary(
            rule_ref=rule.ref,
            rule_name=rule.name,
            kind=rule.kind,
            applied=rule.applied,
            recorded=rule.recorded,
            ledger_count=counts.get(rule.ref, 0) if rule.recorded else None,
        )
        for rule in RULES
    ]


def ledger_entries(
    conn: sqlite3.Connection, rule_ref: str, limit: int, offset: int
) -> LedgerPage:
    """The records behind a rule's count, so any count can be traced to rows."""
    rule = RULES_BY_REF.get(rule_ref)
    if rule is None:
        raise AppError(
            code="UNKNOWN_RULE",
            message=f"There is no rule '{rule_ref}'.",
            status=404,
            detail={"rules": [r.ref for r in RULES]},
        )

    total = conn.execute(
        "SELECT COUNT(*) FROM quality_ledger WHERE rule_ref = ?", (rule_ref,)
    ).fetchone()[0]
    entries = [
        LedgerEntry(
            ledger_id=row[0],
            entity_type=row[1],
            entity_id=row[2],
            action=row[3],
            reason=row[4],
            source_system=row[5],
        )
        for row in conn.execute(
            "SELECT ledger_id, entity_type, entity_id, action, reason, source_system "
            "FROM quality_ledger WHERE rule_ref = ? ORDER BY ledger_id LIMIT ? OFFSET ?",
            (rule_ref, limit, offset),
        )
    ]
    return LedgerPage(
        rule_ref=rule.ref, rule_name=rule.name, total=total,
        limit=limit, offset=offset, entries=entries,
    )
