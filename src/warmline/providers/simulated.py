"""The wired provider. Places nothing, dials nothing, costs nothing."""

from __future__ import annotations

from warmline.providers.base import PlacedCall
from warmline.scenarios import list_scenarios, load_scenario

DEFAULT_SCENARIO = "compliant_meeting_booked"


class SimulatedProvider:
    """Resolves a named scenario to a transcript and returns it immediately.

    The transcript then travels the same path a real one would: normalisation,
    disclosure check, claim check, outcome extraction, write-back.
    """

    name = "simulated"

    def place_call(self, *, to_number: str, scenario: str | None = None) -> PlacedCall:
        chosen = load_scenario(scenario or DEFAULT_SCENARIO)
        transcript = chosen.transcript()

        return PlacedCall(
            conversation_id=transcript.conversation_id,
            status="completed",
            provider=self.name,
            transcript=transcript.to_dict(),
        )

    @staticmethod
    def available_scenarios() -> list[dict]:
        return [
            {"id": s.id, "label": s.label, "description": s.description} for s in list_scenarios()
        ]
