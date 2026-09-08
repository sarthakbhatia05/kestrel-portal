import contextlib
import sqlite3

from kestrel.transform.ledger import Action, QualityLedger
from kestrel.transform.runner import build


class _FakeStep:
    name = "fake"

    def run(self, src, dst, ledger: QualityLedger) -> None:
        dst.execute("INSERT INTO dim_region VALUES (1, 'W', 'West')")
        ledger.record("X9", "fake rule", "region", 99, Action.EXCLUDED, "because")


def _make_source(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE regions (region_id INTEGER)")
    conn.commit()
    conn.close()


def test_build_creates_curated_db_with_ledger_rows(tmp_path):
    source = tmp_path / "source.db"
    curated = tmp_path / "out" / "curated.db"
    _make_source(source)

    result = build(source, curated, steps=[_FakeStep()])

    assert curated.exists()
    assert result.table_counts["dim_region"] == 1
    assert result.ledger_counts == {"X9": 1}

    conn = sqlite3.connect(curated)
    row = conn.execute(
        "SELECT rule_ref, action, reason FROM quality_ledger"
    ).fetchone()
    assert row == ("X9", "EXCLUDED", "because")


def test_build_is_idempotent(tmp_path):
    source = tmp_path / "source.db"
    curated = tmp_path / "curated.db"
    _make_source(source)

    first = build(source, curated, steps=[_FakeStep()])
    second = build(source, curated, steps=[_FakeStep()])

    assert first.table_counts == second.table_counts
    assert first.run_id != second.run_id


def test_failed_build_leaves_previous_curated_db_intact(tmp_path):
    source = tmp_path / "source.db"
    curated = tmp_path / "curated.db"
    _make_source(source)
    build(source, curated, steps=[_FakeStep()])

    class _Exploding:
        name = "boom"

        def run(self, src, dst, ledger):
            raise RuntimeError("step failed")

    with contextlib.suppress(RuntimeError):
        build(source, curated, steps=[_Exploding()])

    conn = sqlite3.connect(curated)
    assert conn.execute("SELECT count(*) FROM dim_region").fetchone()[0] == 1
