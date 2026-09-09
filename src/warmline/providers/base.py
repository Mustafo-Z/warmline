"""The provider seam. SPEC 6.3.

One interface, two implementations, one post-call path. The policy gate,
persistence and every post-call check sit on the far side of this boundary and
are unaware of which provider ran — which is the point: the checks are
exercised identically whether the transcript came from a scenario or a network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PlacedCall:
    """What a provider returns when a call has been handed off.

    `transcript` is populated only by providers that complete the call
    synchronously. A real telephony provider returns None here and delivers the
    transcript later, by webhook.
    """

    conversation_id: str
    status: str
    provider: str
    transcript: dict | None = None
    call_sid: str | None = None


class CallProvider(Protocol):
    name: str

    def place_call(self, *, to_number: str, scenario: str | None = None) -> PlacedCall: ...
