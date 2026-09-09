"""Connection handling and migrations.

SQLite, one file, schema applied from numbered .sql files so that the shape of
the database is reviewable as SQL rather than assembled by ORM metadata.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def to_iso(value: datetime | None) -> str | None:
    """UTC ISO-8601 ending in Z. One format, written in one place."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def connect(path: Path | str = ":memory:") -> sqlite3.Connection:
    """One connection, shared.

    `check_same_thread=False` because the API serves sync endpoints from a
    threadpool. Safe here: sqlite3 is built in serialized mode, the connection
    is in autocommit, and this is a single-user demo. A multi-user deployment
    would want a connection per request against a real server.
    """
    connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def migrate(connection: sqlite3.Connection) -> list[str]:
    """Apply any migrations this database has not seen. Safe to run repeatedly."""
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migration ("
        " version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row["version"] for row in connection.execute("SELECT version FROM schema_migration")}

    newly_applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        connection.executescript(path.read_text())
        connection.execute(
            "INSERT INTO schema_migration (version, applied_at) VALUES (?, ?)",
            (version, to_iso(datetime.now(UTC))),
        )
        newly_applied.append(version)

    return newly_applied


def next_id(connection: sqlite3.Connection, prefix: str) -> str:
    """Readable sequential ids: psp_0001, att_0007.

    A counter table rather than COUNT(*) so that ids are never reused after a
    delete, and readable rather than a UUID because these show up in the UI and
    in commit messages when something goes wrong.
    """
    connection.execute(
        "CREATE TABLE IF NOT EXISTS id_counter (prefix TEXT PRIMARY KEY, value INTEGER NOT NULL)"
    )
    connection.execute(
        "INSERT INTO id_counter (prefix, value) VALUES (?, 1) "
        "ON CONFLICT(prefix) DO UPDATE SET value = value + 1",
        (prefix,),
    )
    row = connection.execute("SELECT value FROM id_counter WHERE prefix = ?", (prefix,)).fetchone()
    return f"{prefix}_{row['value']:04d}"
