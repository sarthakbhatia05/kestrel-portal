import sqlite3
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum


class Action(StrEnum):
    EXCLUDED = "EXCLUDED"
    REPAIRED = "REPAIRED"
    REJECTED = "REJECTED"


class QualityLedger:
    """Accumulates quality events during a build, then writes them in one go.

    The ledger is a product surface, not engineering logging (PRD 6.4): it
    must state in counts what every other screen excludes.
    """

    def __init__(self) -> None:
        self._rows: list[tuple] = []
        self._counts: Counter[str] = Counter()

    def record(
        self,
        rule_ref: str,
        rule_name: str,
        entity_type: str,
        entity_id: str | int | None,
        action: Action,
        reason: str,
        source_system: str | None = None,
    ) -> None:
        self._rows.append(
            (
                rule_ref,
                rule_name,
                entity_type,
                None if entity_id is None else str(entity_id),
                str(action),
                reason,
                source_system,
                datetime.now(UTC).isoformat(timespec="seconds"),
            )
        )
        self._counts[rule_ref] += 1

    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def flush(self, conn: sqlite3.Connection, run_id: str) -> None:
        conn.executemany(
            """
            INSERT INTO quality_ledger (
                run_id, rule_ref, rule_name, entity_type, entity_id,
                action, reason, source_system, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(run_id, *row) for row in self._rows],
        )
        self._rows.clear()
