"""HTTP contract tests. SPEC 6.4, SPEC 9.1.

The assertion this file exists for is
`test_a_blocked_call_never_reaches_the_provider`: the provider double raises if
it is invoked, so the test fails loudly if the gate is ever bypassed.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from tests.conftest import at

from warmline.api.app import create_app
from warmline.providers.simulated import SimulatedProvider
from warmline.storage import repository
from warmline.storage.db import connect, migrate
from warmline.storage.seed import seed

NOW = at("2026-09-09T06:00:00Z")  # Wednesday, 10:00 in Dubai: inside AE hours
SECRET = "test-webhook-secret"


class NeverDials:
    """A provider that fails the test if anything asks it to place a call."""

    name = "simulated"

    def place_call(self, **kwargs):
        raise AssertionError("the policy gate was bypassed and the provider was called")


class Explodes:
    name = "simulated"

    def place_call(self, **kwargs):
        raise RuntimeError("provider unavailable")


def build(provider=None):
    connection = connect()
    migrate(connection)
    seed(connection, NOW)
    app = create_app(
        connection=connection, provider=provider or SimulatedProvider(), clock=lambda: NOW
    )
    return connection, TestClient(app)


@pytest.fixture
def client():
    _connection, test_client = build()
    return test_client


@pytest.fixture
def db_and_client():
    return build()


# --- reads -----------------------------------------------------------------


def test_healthz_states_that_nothing_dials(client):
    body = client.get("/healthz").json()

    assert body["status"] == "ok"
    assert body["places_real_calls"] is False
    assert body["provider"] == "simulated"


def test_prospects_lists_the_seeded_set(client):
    body = client.get("/prospects").json()

    assert len(body["prospects"]) == 6
    assert all(p["is_fixture"] for p in body["prospects"])


def test_an_unknown_prospect_is_a_404(client):
    assert client.get("/prospects/psp_nope").status_code == 404


def test_scenarios_are_listed_for_the_ui(client):
    body = client.get("/scenarios").json()

    assert {s["id"] for s in body["scenarios"]} >= {
        "compliant_meeting_booked",
        "missing_disclosure",
    }
    assert all(s["label"] for s in body["scenarios"])


# --- the dry run -----------------------------------------------------------


def test_policy_check_returns_a_decision_without_writing_anything(db_and_client):
    connection, client = db_and_client

    response = client.post("/prospects/psp_0004/policy-check", json={})

    assert response.status_code == 200
    assert response.json()["primary_reason"] == "NUMBER_SUPPRESSED"
    assert connection.execute("SELECT COUNT(*) FROM call_attempt").fetchone()[0] == 0


def test_policy_check_can_be_asked_about_another_instant(client):
    """20:00 in Dubai: outside the window, without waiting until this evening."""
    response = client.post(
        "/prospects/psp_0001/policy-check", json={"as_of": "2026-09-09T16:00:00Z"}
    )

    assert response.json()["primary_reason"] == "OUTSIDE_CALLING_HOURS"


# --- the gate --------------------------------------------------------------


def test_a_blocked_call_never_reaches_the_provider():
    connection, client = build(provider=NeverDials())

    response = client.post("/prospects/psp_0003/calls", json={})

    assert response.status_code == 409
    assert response.json()["error"] == "policy_blocked"
    assert response.json()["policy"]["primary_reason"] == "CONSENT_WITHDRAWN"


def test_a_blocked_call_is_still_recorded_as_an_attempt():
    connection, client = build(provider=NeverDials())

    attempt_id = client.post("/prospects/psp_0002/calls", json={}).json()["attempt_id"]

    attempt = repository.get_attempt(connection, attempt_id)
    assert attempt["status"] == "blocked"
    assert attempt["dialed_at"] is None
    assert attempt["policy_evaluation_id"]


def test_the_block_response_carries_the_whole_decision():
    """The caller should not need a second request to find out why."""
    _connection, client = build(provider=NeverDials())

    policy = client.post("/prospects/psp_0005/calls", json={}).json()["policy"]

    assert policy["primary_reason"] == "CONSENT_MISSING"
    assert len(policy["checks"]) == 9
    assert policy["config_digest"].startswith("sha256:")


def test_an_allowed_call_runs_the_whole_pipeline(db_and_client):
    connection, client = db_and_client

    response = client.post(
        "/prospects/psp_0001/calls", json={"scenario": "compliant_meeting_booked"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "completed"
    assert body["outcome"]["interest"] == "interested"
    assert body["outcome"]["meeting_requested"] is True
    assert body["outcome"]["violations"] == []
    assert body["outcome"]["transcript_source"] == "scenario"


def test_a_violation_scenario_is_recorded_on_the_outcome(client):
    body = client.post(
        "/prospects/psp_0001/calls", json={"scenario": "invented_pricing_claim"}
    ).json()

    violations = body["outcome"]["violations"]
    assert [v["code"] for v in violations] == ["UNPERMITTED_CLAIM"]
    assert violations[0]["rule_id"] == "PRICE"
    assert body["outcome"]["disclosure_ok"] is True


def test_a_missing_disclosure_is_recorded_on_the_outcome(client):
    body = client.post("/prospects/psp_0001/calls", json={"scenario": "missing_disclosure"}).json()

    assert body["outcome"]["disclosure_ok"] is False
    assert [v["code"] for v in body["outcome"]["violations"]] == ["DISCLOSURE_MISSING"]


def test_an_opt_out_writes_a_suppression_entry(db_and_client):
    """SPEC 4.5: the suppression happens whether or not the agent behaved."""
    connection, client = db_and_client

    client.post("/prospects/psp_0001/calls", json={"scenario": "prospect_opts_out"})

    suppressed = {entry.phone_e164 for entry in repository.list_suppressions(connection)}
    assert "+971501234567" in suppressed


def test_calling_twice_is_stopped_by_the_attempt_limit(client):
    """The limit is one per 24h, and the clock is pinned, so the second is blocked."""
    first = client.post("/prospects/psp_0001/calls", json={"scenario": "compliant_not_interested"})
    second = client.post("/prospects/psp_0001/calls", json={"scenario": "compliant_not_interested"})

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["policy"]["primary_reason"] == "ATTEMPT_LIMIT_REACHED"


def test_a_provider_failure_is_a_502_and_not_a_policy_block():
    """A provider that falls over must never be reported as a compliance block."""
    connection, client = build(provider=Explodes())

    response = client.post("/prospects/psp_0001/calls", json={})

    assert response.status_code == 502
    assert response.json()["error"] == "provider_failed"
    attempt = repository.get_attempt(connection, response.json()["attempt_id"])
    assert attempt["status"] == "failed"
    assert "provider unavailable" in attempt["error"]


def test_the_call_record_can_be_read_back(client):
    attempt_id = client.post(
        "/prospects/psp_0001/calls", json={"scenario": "compliant_meeting_booked"}
    ).json()["attempt_id"]

    body = client.get(f"/calls/{attempt_id}").json()

    assert body["attempt"]["id"] == attempt_id
    assert body["policy"]["decision"] == "allow"
    assert body["outcome"]["transcript"]["turns"]


# --- suppression endpoint --------------------------------------------------


def test_a_number_can_be_suppressed_through_the_api(db_and_client):
    connection, client = db_and_client

    response = client.post("/suppressions", json={"phone_e164": "+971 50 123 4569"})

    assert response.status_code == 201
    assert "+971501234569" in {e.phone_e164 for e in repository.list_suppressions(connection)}


def test_suppressing_an_invalid_number_is_refused(client):
    assert client.post("/suppressions", json={"phone_e164": "12345"}).status_code == 422


# --- the webhook -----------------------------------------------------------


def _live_attempt(connection):
    """An attempt awaiting a webhook, as a real provider would leave it."""
    from warmline.config import load_policy_config
    from warmline.policy.engine import evaluate_pre_dial

    decision = evaluate_pre_dial(
        repository.build_pre_dial_request(connection, "psp_0001", NOW), load_policy_config()
    )
    evaluation_id = repository.insert_policy_evaluation(connection, decision)
    attempt_id = repository.insert_call_attempt(
        connection,
        prospect_id="psp_0001",
        phone_e164="+971501234567",
        status="in_progress",
        policy_evaluation_id=evaluation_id,
        provider="elevenlabs",
        requested_at=NOW,
        dialed_at=NOW,
    )
    repository.update_call_attempt(connection, attempt_id, provider_conversation_id="conv_abc123")
    return attempt_id


def _signed(payload: dict) -> tuple[str, dict]:
    body = json.dumps(payload)
    signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body, {"ElevenLabs-Signature": signature, "Content-Type": "application/json"}


WEBHOOK_PAYLOAD = {
    "conversation_id": "conv_abc123",
    "transcript": {
        "turns": [
            {
                "role": "agent",
                "text": "Hi, I'm an AI assistant calling on behalf of Meridian Communications.",
            },
            {"role": "prospect", "text": "No thanks, nothing at the moment."},
        ]
    },
}


def test_an_unsigned_webhook_writes_nothing(db_and_client, monkeypatch):
    connection, client = db_and_client
    monkeypatch.setenv("WARMLINE_WEBHOOK_SECRET", SECRET)
    attempt_id = _live_attempt(connection)

    response = client.post("/webhooks/elevenlabs/post-call", json=WEBHOOK_PAYLOAD)

    assert response.status_code == 401
    assert repository.get_outcome_for_attempt(connection, attempt_id) is None


def test_a_wrongly_signed_webhook_writes_nothing(db_and_client, monkeypatch):
    connection, client = db_and_client
    monkeypatch.setenv("WARMLINE_WEBHOOK_SECRET", SECRET)
    attempt_id = _live_attempt(connection)
    body, _headers = _signed(WEBHOOK_PAYLOAD)

    response = client.post(
        "/webhooks/elevenlabs/post-call",
        content=body,
        headers={"ElevenLabs-Signature": "0" * 64, "Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert repository.get_outcome_for_attempt(connection, attempt_id) is None


def test_a_correctly_signed_webhook_is_processed(db_and_client, monkeypatch):
    connection, client = db_and_client
    monkeypatch.setenv("WARMLINE_WEBHOOK_SECRET", SECRET)
    attempt_id = _live_attempt(connection)
    body, headers = _signed(WEBHOOK_PAYLOAD)

    response = client.post("/webhooks/elevenlabs/post-call", content=body, headers=headers)

    assert response.status_code == 200
    outcome = repository.get_outcome_for_attempt(connection, attempt_id)
    assert outcome["transcript_source"] == "live"
    assert outcome["interest"] == "not_interested"


def test_a_replayed_webhook_produces_one_outcome(db_and_client, monkeypatch):
    connection, client = db_and_client
    monkeypatch.setenv("WARMLINE_WEBHOOK_SECRET", SECRET)
    _live_attempt(connection)
    body, headers = _signed(WEBHOOK_PAYLOAD)

    client.post("/webhooks/elevenlabs/post-call", content=body, headers=headers)
    second = client.post("/webhooks/elevenlabs/post-call", content=body, headers=headers)

    assert second.json()["status"] == "already_processed"
    assert connection.execute("SELECT COUNT(*) FROM call_outcome").fetchone()[0] == 1


def test_concurrent_requests_do_not_corrupt_each_other():
    """Regression: six simultaneous policy checks used to return 500s.

    The shared SQLite connection was being used from several threadpool
    workers at once, and interleaved cursors handed back rows with empty
    timestamp columns. Found by clicking every button on the page at once,
    not by reasoning about it.
    """
    from concurrent.futures import ThreadPoolExecutor

    _connection, client = build()
    ids = [f"psp_000{n}" for n in range(1, 7)]

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(
            pool.map(lambda i: client.post(f"/prospects/{i}/policy-check", json={}), ids)
        )

    assert [r.status_code for r in responses] == [200] * 6
    assert all(r.json()["prospect_id"] for r in responses)


def test_the_last_outcome_survives_a_later_block(db_and_client):
    """Regression: the row went blank after a completed call was followed by a block.

    The view read the outcome of the *latest attempt*, and the latest attempt
    was the block, which never has one. What a reviewer wants to see is the
    last thing that actually happened on the phone.
    """
    connection, client = db_and_client

    client.post("/prospects/psp_0001/calls", json={"scenario": "compliant_meeting_booked"})
    blocked = client.post(
        "/prospects/psp_0001/calls", json={"scenario": "compliant_not_interested"}
    )
    assert blocked.status_code == 409

    row = next(p for p in client.get("/prospects").json()["prospects"] if p["id"] == "psp_0001")
    assert row["last_outcome"]["interest"] == "interested"
    assert row["last_policy_decision"]["primary_reason"] == "ATTEMPT_LIMIT_REACHED"
