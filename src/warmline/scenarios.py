"""The scenario library. SPEC 8, SPEC 9.2.

One source of truth, used by the CI tests and by the UI's "Simulate call"
button, so the thing demonstrated in the interface is the thing the tests
assert.

Scenario files carry no `source` field. It is set here, to "scenario", when the
transcript is normalised. A scripted conversation cannot label itself as a real
call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from warmline.postcall.transcript import Transcript, normalise_transcript

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    description: str
    raw: dict

    def transcript(self, conversation_id: str | None = None) -> Transcript:
        return normalise_transcript(
            self.raw,
            source="scenario",
            conversation_id=conversation_id or f"sim_{self.id}",
        )


def _load(path: Path) -> Scenario:
    raw = json.loads(path.read_text())
    return Scenario(id=raw["id"], label=raw["label"], description=raw["description"], raw=raw)


def list_scenarios(directory: Path | None = None) -> list[Scenario]:
    return [_load(path) for path in sorted((directory or SCENARIOS_DIR).glob("*.json"))]


def load_scenario(scenario_id: str, directory: Path | None = None) -> Scenario:
    path = (directory or SCENARIOS_DIR) / f"{scenario_id}.json"
    if not path.exists():
        raise KeyError(f"no such scenario: {scenario_id}")
    return _load(path)
