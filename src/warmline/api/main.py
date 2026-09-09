"""Uvicorn entry point: `uvicorn warmline.api.main:app --reload`.

Kept separate from app.py so that importing the application factory has no side
effects — tests build their own app against an in-memory database.
"""

from __future__ import annotations

from warmline.api.app import create_app

app = create_app()
