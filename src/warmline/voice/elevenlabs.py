"""A small client for the parts of the ElevenLabs agents API this project uses.

Four calls: create an agent, update it, issue a session token for the browser,
and fetch a finished conversation. Built on httpx with an injectable transport,
so the tests exercise the real request and response handling without a network
or a key.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

BASE_URL = "https://api.elevenlabs.io"

#: Conversation states that mean "not finished yet, ask again shortly".
PENDING_STATUSES = frozenset({"initiated", "in-progress", "processing"})


class ElevenLabsError(RuntimeError):
    """Anything that went wrong talking to ElevenLabs, with the reason."""


@dataclass(frozen=True)
class SessionToken:
    token: str
    conversation_id: str


@dataclass(frozen=True)
class Conversation:
    status: str
    turns: list[dict]


def to_turns(transcript: list[dict] | None) -> list[dict]:
    """ElevenLabs transcript items to this project's turn shape.

    Their roles are "user" and "agent"; ours are "prospect" and "agent". Items
    with no text — tool calls, silences — are dropped rather than stored as
    empty turns, which the transcript normaliser would rightly refuse.
    """
    roles = {"agent": "agent", "user": "prospect"}
    turns: list[dict] = []
    for item in transcript or []:
        role = roles.get(item.get("role", ""))
        text = (item.get("message") or "").strip()
        if role and text:
            turns.append({"role": role, "text": text})
    return turns


class ElevenLabsClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"xi-api-key": api_key},
            transport=transport,
            timeout=timeout,
        )

    def _send(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise ElevenLabsError(f"could not reach ElevenLabs: {error}") from error
        if response.status_code >= 400:
            raise ElevenLabsError(
                f"ElevenLabs returned {response.status_code} for {method} {path}: "
                f"{response.text[:300]}"
            )
        return response.json() if response.content else {}

    def conversation_token(self, agent_id: str) -> SessionToken:
        """A short-lived token the browser uses to open one WebRTC session."""
        body = self._send("GET", "/v1/convai/conversation/token", params={"agent_id": agent_id})
        token, conversation_id = body.get("token"), body.get("conversation_id")
        if not token or not conversation_id:
            raise ElevenLabsError("token response did not include a token and a conversation_id")
        return SessionToken(token=token, conversation_id=conversation_id)

    def get_conversation_details(self, conversation_id: str) -> dict:
        """The full conversation record, including per-turn timing and call metadata."""
        return self._send("GET", f"/v1/convai/conversations/{conversation_id}")

    def get_conversation(self, conversation_id: str) -> Conversation:
        body = self.get_conversation_details(conversation_id)
        return Conversation(status=body.get("status", ""), turns=to_turns(body.get("transcript")))

    def create_agent(self, definition: dict) -> str:
        body = self._send("POST", "/v1/convai/agents/create", json=definition)
        agent_id = body.get("agent_id")
        if not agent_id:
            raise ElevenLabsError("create agent response did not include an agent_id")
        return agent_id

    def update_agent(self, agent_id: str, definition: dict) -> None:
        self._send("PATCH", f"/v1/convai/agents/{agent_id}", json=definition)
