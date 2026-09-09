"""The HTTP surface. SPEC 6.4.

The only route that can start a call is `POST /prospects/{id}/calls`, and it
calls the policy engine before it calls anything else. A blocked call never
reaches a provider, which is asserted in the tests with a provider double that
fails if it is invoked.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from warmline.config import load_claims_config, load_disclosure_config, load_policy_config
from warmline.policy.engine import evaluate_pre_dial
from warmline.postcall.checks import run_checks
from warmline.postcall.outcome import extract_outcome
from warmline.postcall.transcript import normalise_transcript
from warmline.providers import get_provider
from warmline.providers.simulated import SimulatedProvider
from warmline.storage import repository
from warmline.storage.db import connect, migrate

DEFAULT_DB = Path(os.environ.get("WARMLINE_DB", "warmline.sqlite3"))


class CallRequest(BaseModel):
    scenario: str | None = None


class PolicyCheckRequest(BaseModel):
    as_of: datetime | None = None


class SuppressionRequest(BaseModel):
    phone_e164: str
    reason: str = "manual"
    note: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def create_app(
    *,
    db_path: Path | str | None = None,
    connection: sqlite3.Connection | None = None,
    provider: Any | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build the application.

    `clock` exists so tests can pin the instant. The policy engine is pure and
    takes `now` as an argument; this is the one place that reads a real clock,
    and it is worth being able to control.
    """
    app = FastAPI(
        title="Warmline",
        summary="Policy layer for an outbound AI voice agent. This build places no calls.",
        version="0.1.0",
    )

    # The UI is served from a different port in development. Local origins only.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            # Fallback when 3000 is already taken by something else.
            "http://localhost:3100",
            "http://127.0.0.1:3100",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    shared = connection or connect(db_path or DEFAULT_DB)
    migrate(shared)

    policy_config = load_policy_config()
    claims_config = load_claims_config()
    disclosure_config = load_disclosure_config()
    call_provider = provider or get_provider()
    now_fn = clock or _now

    # One connection, shared, and therefore serialised. sqlite3 lets several
    # threads use one connection with check_same_thread=False, but it does not
    # make interleaved cursors safe: two requests reading at once returned rows
    # with empty timestamp columns, which surfaced as a 500 from datetime
    # parsing. FastAPI serves sync endpoints from a threadpool, so this is
    # reachable from two clicks in a browser, not just in theory.
    #
    # A real deployment would use a connection per request against a database
    # built for concurrency. For a single-user demo, one lock is the honest fix.
    connection_lock = threading.Lock()

    def db():
        with connection_lock:
            yield shared

    # --- reads -------------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "status": "ok",
            "policy_version": policy_config.policy_version,
            "config_digest": policy_config.config_digest,
            "provider": getattr(call_provider, "name", "unknown"),
            "places_real_calls": False,
        }

    @app.get("/scenarios")
    def scenarios() -> dict:
        return {"scenarios": SimulatedProvider.available_scenarios()}

    def _prospect_view(connection: sqlite3.Connection, record) -> dict:
        attempt = repository.latest_attempt(connection, record.id)
        evaluation = repository.latest_evaluation(connection, record.id)
        outcome = repository.latest_outcome(connection, record.id)
        return {
            "id": record.id,
            "full_name": record.full_name,
            "company": record.company,
            "role": record.role,
            "phone_e164": record.phone_e164,
            "timezone": record.timezone,
            "region_profile": record.region_profile,
            "is_fixture": record.is_fixture,
            "last_attempt": attempt,
            "last_policy_decision": evaluation["decision_object"] if evaluation else None,
            "last_outcome": outcome,
        }

    @app.get("/prospects")
    def list_prospects(connection: sqlite3.Connection = Depends(db)) -> dict:
        return {
            "prospects": [
                _prospect_view(connection, record)
                for record in repository.list_prospects(connection)
            ]
        }

    @app.get("/prospects/{prospect_id}")
    def get_prospect(prospect_id: str, connection: sqlite3.Connection = Depends(db)) -> dict:
        record = repository.get_prospect(connection, prospect_id)
        if record is None:
            raise HTTPException(status_code=404, detail="no such prospect")
        view = _prospect_view(connection, record)
        view["attempts"] = [
            repository.get_attempt(connection, attempt.attempt_id)
            for attempt in repository.attempts_for_prospect(connection, prospect_id)
        ]
        return view

    @app.get("/calls/{attempt_id}")
    def get_call(attempt_id: str, connection: sqlite3.Connection = Depends(db)) -> dict:
        attempt = repository.get_attempt(connection, attempt_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="no such attempt")
        return {
            "attempt": attempt,
            "policy": repository.get_policy_evaluation(connection, attempt["policy_evaluation_id"]),
            "outcome": repository.get_outcome_for_attempt(connection, attempt_id),
        }

    @app.get("/suppressions")
    def get_suppressions(connection: sqlite3.Connection = Depends(db)) -> dict:
        return {
            "suppressions": [
                {"phone_e164": e.phone_e164, "reason": e.reason, "source": e.source, "note": e.note}
                for e in repository.list_suppressions(connection)
            ]
        }

    @app.post("/suppressions", status_code=201)
    def post_suppression(
        body: SuppressionRequest, connection: sqlite3.Connection = Depends(db)
    ) -> dict:
        try:
            identifier = repository.add_suppression(
                connection,
                phone_e164=body.phone_e164,
                reason=body.reason,
                source="api",
                note=body.note,
                now=now_fn(),
            )
        except repository.StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"id": identifier, "already_present": identifier is None}

    # --- the policy gate ---------------------------------------------------

    @app.post("/prospects/{prospect_id}/policy-check")
    def policy_check(
        prospect_id: str,
        body: PolicyCheckRequest | None = None,
        connection: sqlite3.Connection = Depends(db),
    ) -> dict:
        """Evaluate the policy and return the decision. Dials nothing, writes nothing.

        A block here is a successful request, not an error: nothing was
        attempted.
        """
        as_of = (body.as_of if body else None) or now_fn()
        try:
            request = repository.build_pre_dial_request(connection, prospect_id, as_of)
        except repository.StorageError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return evaluate_pre_dial(request, policy_config).to_dict()

    @app.post("/prospects/{prospect_id}/calls")
    def place_call(
        prospect_id: str,
        body: CallRequest | None = None,
        connection: sqlite3.Connection = Depends(db),
    ):
        now = now_fn()
        try:
            request = repository.build_pre_dial_request(connection, prospect_id, now)
        except repository.StorageError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

        decision = evaluate_pre_dial(request, policy_config)
        evaluation_id = repository.insert_policy_evaluation(connection, decision)

        # Blocked. Recorded as an attempt, because a block is a record, and the
        # provider is never touched.
        if not decision.allowed:
            attempt_id = repository.insert_call_attempt(
                connection,
                prospect_id=prospect_id,
                phone_e164=request.prospect.phone_e164,
                status="blocked",
                policy_evaluation_id=evaluation_id,
                provider=getattr(call_provider, "name", "unknown"),
                requested_at=now,
            )
            return JSONResponse(
                status_code=409,
                content={
                    "error": "policy_blocked",
                    "attempt_id": attempt_id,
                    "policy": decision.to_dict(),
                },
            )

        scenario = body.scenario if body else None
        attempt_id = repository.insert_call_attempt(
            connection,
            prospect_id=prospect_id,
            phone_e164=request.prospect.phone_e164,
            status="dialing",
            policy_evaluation_id=evaluation_id,
            provider=getattr(call_provider, "name", "unknown"),
            scenario=scenario,
            requested_at=now,
            dialed_at=now,
        )

        try:
            placed = call_provider.place_call(
                to_number=request.prospect.phone_e164, scenario=scenario
            )
        except Exception as error:  # noqa: BLE001 - the provider's failure is data, not a crash
            repository.update_call_attempt(
                connection, attempt_id, status="failed", error=str(error), ended_at=now
            )
            return JSONResponse(
                status_code=502,
                content={
                    "error": "provider_failed",
                    "attempt_id": attempt_id,
                    "detail": str(error),
                    "policy": decision.to_dict(),
                },
            )

        repository.update_call_attempt(
            connection,
            attempt_id,
            provider_conversation_id=placed.conversation_id,
            provider_call_sid=placed.call_sid,
            status=placed.status if placed.transcript is None else "in_progress",
        )

        outcome_payload = None
        if placed.transcript is not None:
            outcome_payload = _process_transcript(
                connection, attempt_id, placed.transcript, source="scenario", now=now
            )

        return JSONResponse(
            status_code=202,
            content={
                "attempt_id": attempt_id,
                "status": repository.get_attempt(connection, attempt_id)["status"],
                "policy": decision.to_dict(),
                "provider": {
                    "name": placed.provider,
                    "conversation_id": placed.conversation_id,
                },
                "outcome": outcome_payload,
            },
        )

    # --- post-call ---------------------------------------------------------

    def _process_transcript(
        connection: sqlite3.Connection,
        attempt_id: str,
        raw_transcript: dict,
        *,
        source: str,
        now: datetime,
    ) -> dict:
        """Normalise, check, extract, write back. One path for every provider."""
        transcript = normalise_transcript(raw_transcript, source=source)
        checks = run_checks(transcript, claims_config, disclosure_config)
        outcome = extract_outcome(transcript, checks)

        attempt = repository.get_attempt(connection, attempt_id)

        # Suppression follows an opt-out regardless of how the agent behaved.
        if outcome.opt_out_requested:
            repository.add_suppression(
                connection,
                phone_e164=attempt["phone_e164"],
                reason="opt_out_in_call",
                source="post_call",
                note=f"opt-out detected in {attempt_id}",
                now=now,
            )

        repository.insert_call_outcome(
            connection,
            call_attempt_id=attempt_id,
            transcript=transcript.to_dict(),
            transcript_source=transcript.source,
            disclosure_ok=checks.disclosure_ok,
            violations=[violation.to_dict() for violation in checks.violations],
            interest=outcome.interest,
            meeting_requested=outcome.meeting_requested,
            opt_out_requested=outcome.opt_out_requested,
            extraction_method=outcome.extraction_method,
            processed_at=now,
            has_news=outcome.has_news,
            news_summary=outcome.news_summary,
            meeting_preferences=outcome.meeting_preferences,
        )
        repository.update_call_attempt(connection, attempt_id, status="completed", ended_at=now)
        return repository.get_outcome_for_attempt(connection, attempt_id)

    @app.post("/webhooks/elevenlabs/post-call")
    async def post_call_webhook(
        request: Request,
        connection: sqlite3.Connection = Depends(db),
        signature: str | None = Header(default=None, alias="ElevenLabs-Signature"),
    ) -> dict:
        raw_body = await request.body()
        secret = os.environ.get("WARMLINE_WEBHOOK_SECRET", "")

        # Verified before the body is parsed. An unverified request writes nothing.
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not secret or not signature or not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="invalid signature")

        payload = json.loads(raw_body)
        conversation_id = payload.get("conversation_id")
        attempt = repository.find_attempt_by_conversation(connection, conversation_id or "")
        if attempt is None:
            raise HTTPException(status_code=404, detail="no attempt for that conversation")

        if repository.get_outcome_for_attempt(connection, attempt["id"]) is not None:
            # A provider retry must not produce a second outcome.
            return {"status": "already_processed", "attempt_id": attempt["id"]}

        outcome = _process_transcript(
            connection,
            attempt["id"],
            payload.get("transcript") or payload,
            source="live",
            now=now_fn(),
        )
        return {"status": "processed", "attempt_id": attempt["id"], "outcome": outcome}

    app.state.connection = shared
    return app
