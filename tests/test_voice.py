"""Live browser voice sessions. The ElevenLabs API is faked; nothing here
needs a key, a network or a microphone.

The assertion this file exists for is
`test_the_checked_transcript_is_the_one_elevenlabs_stored`: the completion
endpoint takes no body, so the text that gets checked can only be what the
server fetched from ElevenLabs, never what a browser claims was said.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.conftest import at

from warmline.agent import load_agent_config
from warmline.api.app import create_app
from warmline.envfile import load_env_file
from warmline.providers.simulated import SimulatedProvider
from warmline.storage.db import connect, migrate
from warmline.storage.seed import seed
from warmline.voice.elevenlabs import (
    Conversation,
    ElevenLabsClient,
    ElevenLabsError,
    SessionToken,
    to_turns,
)
from warmline.voice.settings import VoiceSettings
from warmline.voice.sync_agent import build_definition, remember_agent_id, sync

NOW = at("2026-09-14T06:00:00Z")
OPENING = (
    "Hi, I'm an AI assistant calling on behalf of Meridian Communications. "
    "I'll keep this under a minute. Is now an okay time?"
)


class FakeVoice:
    def __init__(self, conversation: Conversation | None = None, fail_token: bool = False):
        self.conversation = conversation
        self.fail_token = fail_token
        self.tokens = 0
        self.fetches = 0

    def conversation_token(self, agent_id):
        if self.fail_token:
            raise ElevenLabsError("ElevenLabs returned 500")
        self.tokens += 1
        return SessionToken(token=f"tok_{self.tokens}", conversation_id=f"conv_{self.tokens}")

    def get_conversation(self, conversation_id):
        self.fetches += 1
        return self.conversation


def build(fake: FakeVoice, *, passcode: str = "meridian", per_hour: int = 10):
    connection = connect()
    migrate(connection)
    seed(connection, NOW)
    settings = VoiceSettings(
        passcode=passcode,
        agent_id="agent_test",
        api_key="not-a-real-key",
        sessions_per_hour=per_hour,
        max_duration_seconds=180,
    )
    app = create_app(
        connection=connection,
        provider=SimulatedProvider(),
        clock=lambda: NOW,
        voice_settings=settings,
        voice_client=fake,
    )
    return connection, TestClient(app)


def done(*turns: tuple[str, str]) -> Conversation:
    return Conversation(status="done", turns=[{"role": r, "text": t} for r, t in turns])


# --- the ElevenLabs client, against a mocked transport ----------------------


def client_with(handler) -> ElevenLabsClient:
    return ElevenLabsClient("secret-key", transport=httpx.MockTransport(handler))


def test_the_token_request_carries_the_key_and_agent_and_returns_both_ids():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["agent_id"] = request.url.params.get("agent_id")
        seen["key"] = request.headers.get("xi-api-key")
        return httpx.Response(200, json={"token": "tok", "conversation_id": "conv_1"})

    issued = client_with(handler).conversation_token("agent_abc")

    assert seen == {
        "path": "/v1/convai/conversation/token",
        "agent_id": "agent_abc",
        "key": "secret-key",
    }
    assert issued == SessionToken(token="tok", conversation_id="conv_1")


def test_a_token_response_missing_the_conversation_id_is_an_error():
    client = client_with(lambda request: httpx.Response(200, json={"token": "tok"}))

    with pytest.raises(ElevenLabsError):
        client.conversation_token("agent_abc")


def test_an_error_status_from_elevenlabs_is_raised_with_the_reason():
    client = client_with(lambda request: httpx.Response(401, text="invalid api key"))

    with pytest.raises(ElevenLabsError, match="401"):
        client.get_conversation("conv_1")


def test_a_fetched_conversation_maps_roles_and_drops_empty_items():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "status": "done",
                "transcript": [
                    {"role": "agent", "message": OPENING, "time_in_call_secs": 0},
                    {"role": "user", "message": "Go on.", "time_in_call_secs": 4},
                    {"role": "agent", "message": None, "time_in_call_secs": 6},
                ],
            },
        )

    conversation = client_with(handler).get_conversation("conv_1")

    assert conversation.status == "done"
    assert conversation.turns == [
        {"role": "agent", "text": OPENING},
        {"role": "prospect", "text": "Go on."},
    ]


def test_unknown_roles_are_not_invented_into_turns():
    assert to_turns([{"role": "system", "message": "debug"}]) == []


# --- the agent definition ---------------------------------------------------


def test_the_agent_is_built_from_the_repository_files():
    """What the live agent is told is the text a reviewer reads in a diff."""
    agent = load_agent_config()

    definition = build_definition(agent, llm="claude-sonnet-4-5", voice_id="voice_x")
    config = definition["conversation_config"]

    assert config["agent"]["first_message"] == agent.first_turn
    assert config["agent"]["prompt"]["prompt"] == agent.system_prompt
    assert config["conversation"]["max_duration_seconds"] == agent.max_duration_seconds
    assert config["tts"]["voice_id"] == "voice_x"


def test_the_agent_cannot_be_started_without_a_server_issued_token():
    definition = build_definition(load_agent_config(), llm="claude-sonnet-4-5", voice_id="v")

    assert definition["platform_settings"]["auth"]["enable_auth"] is True


def test_sync_creates_once_then_updates_in_place(tmp_path):
    class Recorder:
        def __init__(self):
            self.calls = []

        def create_agent(self, definition):
            self.calls.append("create")
            return "agent_new"

        def update_agent(self, agent_id, definition):
            self.calls.append(f"update:{agent_id}")

    recorder = Recorder()
    definition = {"name": "x"}

    assert sync(recorder, definition, agent_id=None) == ("agent_new", True)
    assert sync(recorder, definition, agent_id="agent_new") == ("agent_new", False)
    assert recorder.calls == ["create", "update:agent_new"]


def test_the_agent_id_is_written_to_env_without_disturbing_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ELEVENLABS_API_KEY=secret\nELEVENLABS_AGENT_ID=old\n")

    remember_agent_id(env, "agent_new")

    assert env.read_text() == "ELEVENLABS_API_KEY=secret\nELEVENLABS_AGENT_ID=agent_new\n"
    assert oct(env.stat().st_mode & 0o777) == "0o600"


# --- the env file -----------------------------------------------------------


def test_env_file_values_load_without_overriding_the_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "WARMLINE_TEST_A=from-file\n"
        'export WARMLINE_TEST_B="quoted value"\n'
        "WARMLINE_TEST_C=from-file\n"
        "not a setting\n"
    )
    monkeypatch.delenv("WARMLINE_TEST_A", raising=False)
    monkeypatch.delenv("WARMLINE_TEST_B", raising=False)
    monkeypatch.setenv("WARMLINE_TEST_C", "already-set")

    loaded = load_env_file(env)

    import os

    assert os.environ["WARMLINE_TEST_A"] == "from-file"
    assert os.environ["WARMLINE_TEST_B"] == "quoted value"
    assert os.environ["WARMLINE_TEST_C"] == "already-set"
    assert sorted(loaded) == ["WARMLINE_TEST_A", "WARMLINE_TEST_B"]
    monkeypatch.delenv("WARMLINE_TEST_A")
    monkeypatch.delenv("WARMLINE_TEST_B")


def test_a_missing_env_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "absent.env") == []


# --- starting a session -----------------------------------------------------


def test_status_reports_what_is_missing_when_voice_is_not_configured():
    _connection, client = build(FakeVoice(), passcode="")

    body = client.get("/voice/status").json()

    assert body["enabled"] is False
    assert "WARMLINE_VOICE_PASSCODE" in body["reason"]


def test_a_session_cannot_start_when_voice_is_not_configured():
    _connection, client = build(FakeVoice(), passcode="")

    assert client.post("/voice/session", json={"passcode": ""}).status_code == 503


def test_a_wrong_passcode_is_refused_and_no_token_is_requested():
    fake = FakeVoice()
    connection, client = build(fake)

    response = client.post("/voice/session", json={"passcode": "guess"})

    assert response.status_code == 401
    assert fake.tokens == 0
    assert connection.execute("SELECT COUNT(*) FROM voice_session").fetchone()[0] == 0


def test_the_right_passcode_issues_a_token_and_records_the_conversation():
    fake = FakeVoice()
    connection, client = build(fake)

    body = client.post("/voice/session", json={"passcode": "meridian"}).json()

    assert body["conversation_token"] == "tok_1"
    assert body["conversation_id"] == "conv_1"
    assert body["max_duration_seconds"] == 180
    row = connection.execute("SELECT status FROM voice_session").fetchone()
    assert row["status"] == "issued"


def test_the_api_key_is_never_returned_to_the_browser():
    _connection, client = build(FakeVoice())

    text = client.post("/voice/session", json={"passcode": "meridian"}).text

    assert "not-a-real-key" not in text


def test_sessions_are_capped_per_hour():
    _connection, client = build(FakeVoice(), per_hour=2)

    codes = [
        client.post("/voice/session", json={"passcode": "meridian"}).status_code for _ in range(3)
    ]

    assert codes == [200, 200, 429]


def test_an_elevenlabs_failure_is_a_502_and_records_nothing():
    connection, client = build(FakeVoice(fail_token=True))

    response = client.post("/voice/session", json={"passcode": "meridian"})

    assert response.status_code == 502
    assert connection.execute("SELECT COUNT(*) FROM voice_session").fetchone()[0] == 0


# --- completing a session ---------------------------------------------------


def start(client) -> str:
    return client.post("/voice/session", json={"passcode": "meridian"}).json()["conversation_id"]


def test_only_a_conversation_this_service_started_can_be_checked():
    fake = FakeVoice(done(("agent", OPENING)))
    _connection, client = build(fake)

    response = client.post("/voice/sessions/conv_somebody_else/complete")

    assert response.status_code == 404
    assert fake.fetches == 0


def test_a_conversation_still_processing_asks_the_browser_to_wait():
    _connection, client = build(FakeVoice(Conversation(status="processing", turns=[])))
    conversation_id = start(client)

    response = client.post(f"/voice/sessions/{conversation_id}/complete")

    assert response.status_code == 202
    assert response.json() == {"status": "processing"}


def test_the_checked_transcript_is_the_one_elevenlabs_stored():
    """A browser cannot submit a cleaner version of what the agent said."""
    stored = done(
        ("agent", OPENING),
        ("prospect", "What does it cost?"),
        ("agent", "Our retainers start at 5000 dollars a month."),
    )
    _connection, client = build(FakeVoice(stored))
    conversation_id = start(client)

    body = client.post(
        f"/voice/sessions/{conversation_id}/complete",
        json={"transcript": {"turns": [{"role": "agent", "text": OPENING}]}},
    ).json()

    assert [v["rule_id"] for v in body["checks"]["violations"]] == ["PRICE"]
    assert body["transcript"]["source"] == "live"
    assert len(body["transcript"]["turns"]) == 3


def test_a_live_transcript_is_stored_labelled_live():
    connection, client = build(FakeVoice(done(("agent", OPENING), ("prospect", "Not now."))))
    conversation_id = start(client)

    client.post(f"/voice/sessions/{conversation_id}/complete")

    row = connection.execute("SELECT * FROM voice_session").fetchone()
    assert row["status"] == "processed"
    assert row["transcript_source"] == "live"
    assert json.loads(row["transcript_json"])["source"] == "live"


def test_a_missing_disclosure_in_a_live_call_is_caught():
    live = done(("agent", "Hello, calling from Meridian Communications."), ("prospect", "Who?"))
    _connection, client = build(FakeVoice(live))
    conversation_id = start(client)

    body = client.post(f"/voice/sessions/{conversation_id}/complete").json()

    assert body["checks"]["disclosure_ok"] is False
    assert "DISCLOSURE_MISSING" in [v["code"] for v in body["checks"]["violations"]]


def test_completing_twice_returns_the_stored_result_without_refetching():
    fake = FakeVoice(done(("agent", OPENING), ("prospect", "Not now.")))
    _connection, client = build(fake)
    conversation_id = start(client)

    first = client.post(f"/voice/sessions/{conversation_id}/complete").json()
    second = client.post(f"/voice/sessions/{conversation_id}/complete").json()

    assert first == second
    assert fake.fetches == 1


def test_an_empty_conversation_is_recorded_as_failed():
    _connection, client = build(FakeVoice(Conversation(status="done", turns=[])))
    conversation_id = start(client)

    response = client.post(f"/voice/sessions/{conversation_id}/complete")

    assert response.status_code == 422
    assert "before anything was said" in response.json()["error"]


def test_a_live_result_has_the_same_shape_as_a_scenario_result():
    """The page renders both with the same components, so the shapes must agree."""
    _connection, client = build(FakeVoice(done(("agent", OPENING), ("prospect", "Not now."))))
    conversation_id = start(client)

    live = client.post(f"/voice/sessions/{conversation_id}/complete").json()
    scripted = client.get("/scenarios/compliant_not_interested").json()

    assert set(live["checks"]) == set(scripted["checks"])
    assert set(live["outcome"]) == set(scripted["outcome"])


def test_recent_sessions_lists_only_processed_conversations():
    _connection, client = build(FakeVoice(done(("agent", OPENING), ("prospect", "Not now."))))
    processed = start(client)
    client.post(f"/voice/sessions/{processed}/complete")
    start(client)  # issued, never completed

    sessions = client.get("/voice/sessions").json()["sessions"]

    assert [s["conversation_id"] for s in sessions] == [processed]
