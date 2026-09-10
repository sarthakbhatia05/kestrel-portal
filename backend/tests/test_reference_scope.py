"""Scope options are derived from the data, never hard-coded.

A dropdown that offers a period the warehouse has no rows for produces
five empty cards and a user who thinks the build is broken. So the option
list is computed from the order dates actually present.
"""

import sqlite3

import pytest

from kestrel.reference import scope
from kestrel.transform.runner import build
from kestrel.transform.steps import s00_reference, s20_orders


@pytest.fixture
def conn(tmp_path, source_db):
    path = tmp_path / "curated.db"
    build(source_db, path, steps=[s00_reference, s20_orders])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def test_regions_come_from_the_curated_dimension(conn):
    regions = scope.list_regions(conn)
    assert [r.region_name for r in regions] == ["West", "South"]
    assert regions[0].region_id == 1


def test_periods_offer_only_months_the_data_has_rows_in(conn):
    """The fixture's orders fall in January, April and May 2026 only."""
    months = [p.value for p in scope.available_periods(conn) if p.kind == "month"]
    assert months == ["2026-05", "2026-04", "2026-01"]


def test_periods_offer_the_quarters_those_months_fall_in(conn):
    quarters = [p.value for p in scope.available_periods(conn) if p.kind == "quarter"]
    assert quarters == ["FY27Q1", "FY26Q4"]


def test_periods_are_labelled_for_reading_not_parsing(conn):
    labels = {p.value: p.label for p in scope.available_periods(conn)}
    assert labels["2026-04"] == "April 2026"
    assert labels["FY27Q1"] == "FY27 Q1"


def test_latest_is_offered_first_so_the_dropdown_is_what_the_api_returns(conn):
    """The default scope is a real option, not a frontend special case."""
    first = scope.available_periods(conn)[0]
    assert (first.value, first.kind) == ("latest", "relative")


def test_periods_run_newest_first(conn):
    values = [p.value for p in scope.available_periods(conn)]
    assert values.index("FY27Q1") < values.index("FY26Q4")


def test_no_periods_when_there_are_no_orders(tmp_path, source_db):
    """Only 'latest' survives: an empty dataset must not invent a range."""
    path = tmp_path / "empty.db"
    build(source_db, path, steps=[s00_reference, s20_orders])
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("DELETE FROM fact_order_line")
    assert [p.value for p in scope.available_periods(c)] == ["latest"]
