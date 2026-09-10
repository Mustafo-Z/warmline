"""Uvicorn entry point: `uvicorn warmline.api.main:app`.

Kept separate from app.py so that importing the application factory has no side
effects — tests build their own app against an in-memory database.

On a fresh deployment the database file does not exist yet, so this migrates
and seeds it. Seeding is skipped if there are already prospects, so a restart
never overwrites what a reviewer has been clicking on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from warmline.api.app import DEFAULT_DB, create_app
from warmline.storage.db import connect, migrate
from warmline.storage.seed import seed


def _bootstrap() -> None:
    connection = connect(DEFAULT_DB)
    migrate(connection)
    if connection.execute("SELECT COUNT(*) AS n FROM prospect").fetchone()["n"] == 0:
        seed(connection, datetime.now(UTC))
    connection.close()


_bootstrap()

app = create_app()
