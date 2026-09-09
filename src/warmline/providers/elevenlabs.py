"""The unwired provider. Written to the seam, never instantiated.

This build places no telephone calls (SPEC 2.1). The class exists so that the
boundary between "decide whether to call" and "call" is visible and typed,
rather than being an argument about what the code would look like. It has never
run against a live network, and the README says so.

Constructing it requires WARMLINE_ALLOW_LIVE_CALLS=1 in the environment. That
is not security — it is a speed bump, so that wiring a real provider has to be
a deliberate act rather than a config typo.
"""

from __future__ import annotations

import os

from warmline.providers.base import PlacedCall

OUTBOUND_CALL_URL = "https://api.elevenlabs.io/v1/convai/twilio/outbound-call"


class LiveCallsNotEnabled(RuntimeError):
    pass


class ElevenLabsProvider:
    name = "elevenlabs"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        agent_id: str | None = None,
        agent_phone_number_id: str | None = None,
    ) -> None:
        if os.environ.get("WARMLINE_ALLOW_LIVE_CALLS") != "1":
            raise LiveCallsNotEnabled(
                "This build does not place calls. Set WARMLINE_ALLOW_LIVE_CALLS=1 only if you "
                "have read docs/SPEC.md section 2 and the number is one you own."
            )
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self.agent_id = agent_id or os.environ.get("ELEVENLABS_AGENT_ID", "")
        self.agent_phone_number_id = agent_phone_number_id or os.environ.get(
            "ELEVENLABS_AGENT_PHONE_NUMBER_ID", ""
        )

    def place_call(self, *, to_number: str, scenario: str | None = None) -> PlacedCall:
        """Hand the call to ElevenLabs, which owns the media path and Twilio.

        The transcript is not returned here. It arrives later on the post-call
        webhook, which is why PlacedCall.transcript is None.
        """
        import httpx  # imported here so the dependency is not needed to import this module

        response = httpx.post(
            OUTBOUND_CALL_URL,
            headers={"xi-api-key": self.api_key},
            json={
                "agent_id": self.agent_id,
                "agent_phone_number_id": self.agent_phone_number_id,
                "to_number": to_number,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        body = response.json()

        return PlacedCall(
            conversation_id=body.get("conversation_id", ""),
            status="dialing",
            provider=self.name,
            call_sid=body.get("callSid"),
        )
