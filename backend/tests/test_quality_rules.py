"""The rule catalogue and the ledger entries behind each rule (PRD 6.4)."""

import sqlite3

import pytest

from kestrel.exceptions import AppError
from kestrel.quality import rules
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders, s30_deliveries, s40_returns


def _curated(tmp_path, source_db, steps):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=steps)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture
def conn(tmp_path, source_db):
    return _curated(tmp_path, source_db, [s00_reference, s20_orders, s30_deliveries, s40_returns])


def _by_ref(summaries):
    return {s.rule_ref: s for s in summaries}


def test_catalogue_lists_every_prd_rule_in_order(conn):
    refs = [s.rule_ref for s in rules.catalogue(conn)]
    assert refs == ["N1", "N2", "N3", "N4", "N5", "N6", "X1", "X2", "X3", "X4", "X5"]


def test_catalogue_counts_ledger_entries_per_rule(conn):
    by_ref = _by_ref(rules.catalogue(conn))
    assert by_ref["N1"].ledger_count == 1  # line 7's implausible case pack
    assert by_ref["N3"].ledger_count == 1  # delivery 4's unparseable arrival
    assert by_ref["N4"].ledger_count == 1  # CN002's negative quantity
    assert by_ref["X1"].ledger_count == 1  # outlet 4
    assert by_ref["X2"].ledger_count == 1  # TST1
    assert by_ref["X4"].ledger_count == 1  # line 4, cancelled
    assert by_ref["X5"].ledger_count == 1  # outlet 6 shares outlet 2's GST


def test_rules_that_write_no_ledger_entries_have_no_count_rather_than_zero(conn):
    """Zero would claim the rule ran and found nothing."""
    by_ref = _by_ref(rules.catalogue(conn))
    for ref in ("N2", "N6", "X3"):
        assert by_ref[ref].recorded is False
        assert by_ref[ref].ledger_count is None


def test_a_recorded_rule_that_never_fired_reads_zero_not_missing(tmp_path, source_db):
    # Only the reference step ran: no order, delivery or return rule fired.
    conn = _curated(tmp_path, source_db, [s00_reference])
    by_ref = _by_ref(rules.catalogue(conn))
    assert by_ref["N1"].ledger_count == 0
    assert by_ref["N3"].ledger_count == 0
    assert by_ref["X4"].ledger_count == 0


def test_x3_is_marked_as_applied_at_query_time(conn):
    assert _by_ref(rules.catalogue(conn))["X3"].applied == "query"


def test_ledger_entries_trace_a_count_to_the_affected_record(conn):
    page = rules.ledger_entries(conn, "X4", limit=50, offset=0)
    assert page.total == 1
    [entry] = page.entries
    assert entry.entity_type == "order_line"
    assert entry.entity_id == "4"
    assert entry.action == "EXCLUDED"
    assert "CANCELLED" in entry.reason
    assert entry.source_system == "ERP_WEB"


def test_ledger_entries_page_with_offset(conn):
    page = rules.ledger_entries(conn, "X4", limit=50, offset=1)
    assert page.total == 1
    assert page.entries == []


def test_ledger_entries_for_an_unrecorded_rule_are_empty(conn):
    page = rules.ledger_entries(conn, "X3", limit=50, offset=0)
    assert page.total == 0
    assert page.entries == []


def test_ledger_entries_reject_a_rule_that_does_not_exist(conn):
    with pytest.raises(AppError) as raised:
        rules.ledger_entries(conn, "X9", limit=50, offset=0)
    assert raised.value.code == "UNKNOWN_RULE"
    assert raised.value.status == 404
