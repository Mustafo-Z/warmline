"""Provider selection. The default is, and in this build always is, simulated."""

from __future__ import annotations

import os

from warmline.providers.base import CallProvider, PlacedCall
from warmline.providers.simulated import SimulatedProvider

__all__ = ["CallProvider", "PlacedCall", "SimulatedProvider", "get_provider"]


def get_provider(name: str | None = None) -> CallProvider:
    chosen = name or os.environ.get("CALL_PROVIDER", "simulated")
    if chosen == "simulated":
        return SimulatedProvider()
    if chosen == "elevenlabs":
        from warmline.providers.elevenlabs import ElevenLabsProvider

        return ElevenLabsProvider()
    raise ValueError(f"unknown call provider: {chosen}")
