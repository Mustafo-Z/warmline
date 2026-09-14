"""Reading the agent's version-controlled configuration.

The prompt, the pinned first turn and the agent settings live in `agent/` as
files rather than inline in code or only in a provider dashboard (SPEC 5.1).
This module is the only thing that reads them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = REPO_ROOT / "agent"

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_notes(text: str) -> str:
    """Drop the explanatory HTML comment block, keep the content."""
    return _HTML_COMMENT.sub("", text).strip()


@dataclass(frozen=True)
class AgentConfig:
    name: str
    principal: str
    language: str
    system_prompt: str
    first_turn: str
    max_duration_seconds: int
    end_call_on_voicemail: bool
    end_call_when: str
    voice_name: str
    voice_id: str
    tts_model: str
    voice_speed: float
    provider_name: str
    provider_wired: bool


def load_first_turn(agent_dir: Path | None = None) -> str:
    """The pinned opening utterance, exactly as spoken. SPEC 4.4."""
    directory = agent_dir or AGENT_DIR
    return _strip_notes((directory / "first_turn.md").read_text())


def load_system_prompt(agent_dir: Path | None = None) -> str:
    directory = agent_dir or AGENT_DIR
    return _strip_notes((directory / "system_prompt.md").read_text())


def load_agent_config(agent_dir: Path | None = None) -> AgentConfig:
    directory = agent_dir or AGENT_DIR
    raw = json.loads((directory / "agent_config.json").read_text())
    conversation = raw["conversation"]
    voice = raw.get("voice") or {}
    provider = raw["provider"]

    return AgentConfig(
        name=raw["name"],
        principal=raw["principal"],
        language=raw["language"],
        system_prompt=load_system_prompt(directory),
        first_turn=load_first_turn(directory),
        max_duration_seconds=int(conversation["max_duration_seconds"]),
        end_call_on_voicemail=bool(conversation["end_call_on_voicemail"]),
        end_call_when=conversation.get("end_call_when", ""),
        voice_name=voice.get("name", ""),
        voice_id=voice.get("voice_id", ""),
        tts_model=voice.get("tts_model", "eleven_flash_v2"),
        voice_speed=float(voice.get("speed", 1.0)),
        provider_name=provider["name"],
        provider_wired=bool(provider["wired"]),
    )
