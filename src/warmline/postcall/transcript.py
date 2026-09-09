"""Normalising a transcript into the one shape every checker consumes. SPEC 6.2."""

from __future__ import annotations

from dataclasses import dataclass

VALID_ROLES = frozenset({"agent", "prospect"})
VALID_SOURCES = frozenset({"scenario", "live"})


class TranscriptError(ValueError):
    pass


@dataclass(frozen=True)
class Turn:
    index: int
    role: str
    text: str


@dataclass(frozen=True)
class Transcript:
    conversation_id: str
    source: str
    turns: tuple[Turn, ...]

    @property
    def agent_turns(self) -> tuple[Turn, ...]:
        return tuple(turn for turn in self.turns if turn.role == "agent")

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "source": self.source,
            "turns": [
                {"index": turn.index, "role": turn.role, "text": turn.text} for turn in self.turns
            ],
        }


def normalise_transcript(
    raw: dict, *, source: str, conversation_id: str | None = None
) -> Transcript:
    """Build a Transcript, with `source` supplied by the caller.

    `source` is never read from the payload, even if the payload carries one.
    A scripted conversation cannot label itself as a real call, whether by
    mistake or otherwise (SPEC 6.2).
    """
    if source not in VALID_SOURCES:
        raise TranscriptError(f"source must be one of {sorted(VALID_SOURCES)}, got {source!r}")

    raw_turns = raw.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise TranscriptError("transcript has no turns")

    turns = []
    for position, entry in enumerate(raw_turns):
        role = entry.get("role")
        if role not in VALID_ROLES:
            raise TranscriptError(f"turn {position} has role {role!r}")
        text = (entry.get("text") or "").strip()
        if not text:
            raise TranscriptError(f"turn {position} has no text")
        turns.append(Turn(index=position, role=role, text=text))

    return Transcript(
        conversation_id=conversation_id or raw.get("conversation_id") or "unknown",
        source=source,
        turns=tuple(turns),
    )
