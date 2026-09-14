"""Voice session configuration, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceSettings:
    passcode: str
    agent_id: str
    api_key: str
    sessions_per_hour: int
    max_duration_seconds: int

    @property
    def enabled(self) -> bool:
        return bool(self.passcode and self.agent_id and self.api_key)

    @property
    def missing(self) -> list[str]:
        names = {
            "WARMLINE_VOICE_PASSCODE": self.passcode,
            "ELEVENLABS_AGENT_ID": self.agent_id,
            "ELEVENLABS_API_KEY": self.api_key,
        }
        return [name for name, value in names.items() if not value]

    @classmethod
    def from_env(cls, max_duration_seconds: int) -> VoiceSettings:
        return cls(
            passcode=os.environ.get("WARMLINE_VOICE_PASSCODE", ""),
            agent_id=os.environ.get("ELEVENLABS_AGENT_ID", ""),
            api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
            sessions_per_hour=int(os.environ.get("WARMLINE_VOICE_SESSIONS_PER_HOUR", "10")),
            max_duration_seconds=max_duration_seconds,
        )
