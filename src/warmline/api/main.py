"""Uvicorn entry point: `uvicorn warmline.api.main:app`.

Kept separate from app.py so that importing the application factory has no side
effects — tests build their own app against an in-memory database.

Loads .env first, so the voice settings and any WARMLINE_DB override are in the
environment before the application reads them. Then migrates, and seeds only if
there are no prospects, so a restart never overwrites what a reviewer has been
clicking on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from warmline.envfile import load_env_file

load_env_file()

from warmline.api.app import DEFAULT_DB, create_app  # noqa: E402
from warmline.storage.db import connect, migrate  # noqa: E402
from warmline.storage.seed import seed  # noqa: E402


def _bootstrap() -> None:
    connection = connect(DEFAULT_DB)
    migrate(connection)
    if connection.execute("SELECT COUNT(*) AS n FROM prospect").fetchone()["n"] == 0:
        seed(connection, datetime.now(UTC))
    connection.close()


_bootstrap()

app = create_app()
