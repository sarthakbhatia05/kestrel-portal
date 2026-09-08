import sqlite3

import pytest

from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference


@pytest.fixture
def curated(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference])
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _outlet(conn, outlet_id):
    return conn.execute(
        "SELECT * FROM dim_outlet WHERE outlet_id = ?", (outlet_id,)
    ).fetchone()


def test_city_variants_are_mapped_to_a_canonical_form(curated):
    assert _outlet(curated, 1)["city"] == "Bengaluru"
    assert _outlet(curated, 2)["city"] == "Bengaluru"
    assert _outlet(curated, 2)["city_raw"] == "Bangalore"
    assert _outlet(curated, 6)["city"] == "Delhi"


def test_deleted_outlet_is_flagged_not_removed(curated):
    row = _outlet(curated, 4)
    assert row is not None, "excluded rows are retained (PRD 6.3)"
    assert row["is_excluded"] == 1
    assert "X1" in row["exclusion_rules"]


def test_test_outlet_is_excluded_by_code_prefix(curated):
    assert _outlet(curated, 5)["is_excluded"] == 1
    assert "X2" in _outlet(curated, 5)["exclusion_rules"]


def test_duplicate_gst_keeps_the_lowest_outlet_id_and_excludes_the_rest(curated):
    assert _outlet(curated, 2)["is_excluded"] == 0
    assert _outlet(curated, 6)["is_excluded"] == 1
    assert "X5" in _outlet(curated, 6)["exclusion_rules"]


def test_closed_outlet_is_retained_and_not_flagged(curated):
    """X3 is period-scoped, so it is applied at query time, not at build time."""
    row = _outlet(curated, 3)
    assert row["is_excluded"] == 0
    assert row["closed_date"] == "2025-06-30"


def test_every_exclusion_is_recorded_in_the_ledger(curated):
    counts = dict(
        curated.execute(
            "SELECT rule_ref, count(*) FROM quality_ledger GROUP BY rule_ref"
        ).fetchall()
    )
    assert counts["X1"] == 1
    assert counts["X2"] == 1
    assert counts["X5"] == 1
    assert counts["N5"] == 2  # Bangalore and New Delhi were repaired
