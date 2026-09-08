import sqlite3

import pytest

from kestrel.database import curated_connection, source_connection


def test_curated_connection_can_write(tmp_path):
    db = tmp_path / "nested" / "curated.db"
    with curated_connection(db) as conn:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    assert db.exists()


def test_source_connection_rejects_writes(tmp_path):
    db = tmp_path / "source.db"
    with curated_connection(db) as conn:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.commit()

    with source_connection(db) as conn:
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO t VALUES (1)")


def test_rows_are_mappings(tmp_path):
    db = tmp_path / "curated.db"
    with curated_connection(db) as conn:
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.execute("INSERT INTO t VALUES (7)")
        row = conn.execute("SELECT a FROM t").fetchone()
        assert row["a"] == 7
