import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def source_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the source database read-only.

    NF6 requires that source data is never mutated. Read-only mode is
    enforced by SQLite rather than by convention, so a write attempt raises
    instead of succeeding quietly. Only kestrel.transform may call this.
    """
    if not path.exists():
        raise FileNotFoundError(f"Source database not found: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        yield _configure(conn)
    finally:
        conn.close()


@contextmanager
def curated_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the curated database read-write, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        yield _configure(conn)
    finally:
        conn.close()


def open_curated_readonly(path: Path) -> sqlite3.Connection:
    """Open the curated database read-only for serving requests.

    Caller closes. Used by FastAPI dependencies, which cannot use a
    context manager across the request boundary.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Curated database not found: {path}. "
            "Run `python -m kestrel.transform build` first."
        )
    return _configure(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True))
