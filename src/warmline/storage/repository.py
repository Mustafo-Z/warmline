"""Reads and writes. The only module that knows SQL.

The function that matters most here is `build_pre_dial_request`: it is the seam
between storage and the pure policy engine. The engine reads nothing; this
assembles everything it needs and hands it over.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from warmline.phone import normalise_e164
from warmline.policy.models import (
    AttemptRecord,
    Consent,
    PolicyDecision,
    PreDialRequest,
    SuppressionEntry,
)
from warmline.storage.db import from_iso, next_id, to_iso
from warmline.storage.models import ProspectRecord


class StorageError(ValueError):
    """Raised when a write would put something invalid in the database."""


def _require_e164(raw: str) -> str:
    normalised = normalise_e164(raw)
    if normalised is None:
        raise StorageError(f"not a valid E.164 number: {raw!r}")
    return normalised


# --- prospects -------------------------------------------------------------


def insert_prospect(
    connection: sqlite3.Connection,
    *,
    full_name: str,
    company: str,
    phone_e164: str,
    timezone: str,
    region_profile: str,
    now: datetime,
    role: str | None = None,
    language: str = "en",
    is_fixture: bool = True,
    prospect_id: str | None = None,
) -> ProspectRecord:
    identifier = prospect_id or next_id(connection, "psp")
    stamp = to_iso(now)
    normalised = _require_e164(phone_e164)

    connection.execute(
        "INSERT INTO prospect (id, full_name, company, role, phone_e164, timezone,"
        " region_profile, language, is_fixture, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            identifier,
            full_name,
            company,
            role,
            normalised,
            timezone,
            region_profile,
            language,
            1 if is_fixture else 0,
            stamp,
            stamp,
        ),
    )
    return get_prospect(connection, identifier)  # type: ignore[return-value]


def _prospect_from_row(row: sqlite3.Row) -> ProspectRecord:
    return ProspectRecord(
        id=row["id"],
        full_name=row["full_name"],
        company=row["company"],
        role=row["role"],
        phone_e164=row["phone_e164"],
        timezone=row["timezone"],
        region_profile=row["region_profile"],
        language=row["language"],
        is_fixture=bool(row["is_fixture"]),
    )


def get_prospect(connection: sqlite3.Connection, prospect_id: str) -> ProspectRecord | None:
    row = connection.execute("SELECT * FROM prospect WHERE id = ?", (prospect_id,)).fetchone()
    return _prospect_from_row(row) if row else None


def list_prospects(connection: sqlite3.Connection) -> list[ProspectRecord]:
    rows = connection.execute("SELECT * FROM prospect ORDER BY id").fetchall()
    return [_prospect_from_row(row) for row in rows]


# --- consent ---------------------------------------------------------------


def insert_consent(
    connection: sqlite3.Connection,
    *,
    prospect_id: str,
    lawful_basis: str,
    captured_at: datetime,
    evidence: str,
    now: datetime,
    expires_at: datetime | None = None,
    withdrawn_at: datetime | None = None,
) -> str:
    identifier = next_id(connection, "con")
    connection.execute(
        "INSERT INTO consent (id, prospect_id, lawful_basis, captured_at, expires_at,"
        " evidence, withdrawn_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            identifier,
            prospect_id,
            lawful_basis,
            to_iso(captured_at),
            to_iso(expires_at),
            evidence,
            to_iso(withdrawn_at),
            to_iso(now),
        ),
    )
    return identifier


def get_consent(connection: sqlite3.Connection, prospect_id: str) -> Consent | None:
    """The most recently captured consent record for a prospect, if any."""
    row = connection.execute(
        "SELECT * FROM consent WHERE prospect_id = ? ORDER BY captured_at DESC, id DESC LIMIT 1",
        (prospect_id,),
    ).fetchone()
    if row is None:
        return None
    return Consent(
        lawful_basis=row["lawful_basis"],
        captured_at=from_iso(row["captured_at"]),  # type: ignore[arg-type]
        expires_at=from_iso(row["expires_at"]),
        withdrawn_at=from_iso(row["withdrawn_at"]),
        evidence=row["evidence"],
    )


def withdraw_consent(connection: sqlite3.Connection, prospect_id: str, *, when: datetime) -> None:
    """Withdrawal is permanent: it stamps the existing row rather than adding one."""
    connection.execute(
        "UPDATE consent SET withdrawn_at = ? WHERE prospect_id = ? AND withdrawn_at IS NULL",
        (to_iso(when), prospect_id),
    )


# --- suppression -----------------------------------------------------------


def add_suppression(
    connection: sqlite3.Connection,
    *,
    phone_e164: str,
    reason: str,
    source: str,
    now: datetime,
    note: str | None = None,
) -> str | None:
    """Add a number to the suppression list. Idempotent: already there is fine."""
    normalised = _require_e164(phone_e164)
    identifier = next_id(connection, "sup")
    try:
        connection.execute(
            "INSERT INTO suppression_entry (id, phone_e164, reason, source, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (identifier, normalised, reason, source, note, to_iso(now)),
        )
    except sqlite3.IntegrityError:
        return None
    return identifier


def list_suppressions(connection: sqlite3.Connection) -> list[SuppressionEntry]:
    rows = connection.execute("SELECT * FROM suppression_entry ORDER BY created_at").fetchall()
    return [
        SuppressionEntry(
            phone_e164=row["phone_e164"],
            reason=row["reason"],
            source=row["source"],
            note=row["note"],
        )
        for row in rows
    ]


# --- policy evaluations ----------------------------------------------------


def insert_policy_evaluation(
    connection: sqlite3.Connection, decision: PolicyDecision, *, phase: str = "pre_dial"
) -> str:
    """Store the SPEC 4.3 object verbatim, so it can be re-read exactly."""
    identifier = next_id(connection, "pev")
    connection.execute(
        "INSERT INTO policy_evaluation (id, prospect_id, phase, decision, primary_reason,"
        " checks_json, policy_version, config_digest, evaluated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            identifier,
            decision.prospect_id,
            phase,
            decision.decision,
            decision.primary_reason,
            json.dumps(decision.to_dict()),
            decision.policy_version,
            decision.config_digest,
            to_iso(decision.evaluated_at),
        ),
    )
    return identifier


def get_policy_evaluation(connection: sqlite3.Connection, evaluation_id: str) -> dict | None:
    row = connection.execute(
        "SELECT checks_json FROM policy_evaluation WHERE id = ?", (evaluation_id,)
    ).fetchone()
    return json.loads(row["checks_json"]) if row else None


# --- call attempts ---------------------------------------------------------


def insert_call_attempt(
    connection: sqlite3.Connection,
    *,
    prospect_id: str,
    phone_e164: str,
    status: str,
    policy_evaluation_id: str,
    provider: str,
    requested_at: datetime,
    scenario: str | None = None,
    dialed_at: datetime | None = None,
) -> str:
    identifier = next_id(connection, "att")
    connection.execute(
        "INSERT INTO call_attempt (id, prospect_id, phone_e164, status, policy_evaluation_id,"
        " provider, scenario, requested_at, dialed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            identifier,
            prospect_id,
            _require_e164(phone_e164),
            status,
            policy_evaluation_id,
            provider,
            scenario,
            to_iso(requested_at),
            to_iso(dialed_at),
        ),
    )
    return identifier


def update_call_attempt(connection: sqlite3.Connection, attempt_id: str, **fields) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "provider_conversation_id",
        "provider_call_sid",
        "dialed_at",
        "ended_at",
        "duration_seconds",
        "error",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise StorageError(f"cannot update unknown call_attempt fields: {sorted(unknown)}")

    values = {
        key: to_iso(value) if isinstance(value, datetime) else value
        for key, value in fields.items()
    }
    assignments = ", ".join(f"{key} = ?" for key in values)
    connection.execute(
        f"UPDATE call_attempt SET {assignments} WHERE id = ?",
        (*values.values(), attempt_id),
    )


def _attempt_from_row(row: sqlite3.Row) -> AttemptRecord:
    return AttemptRecord(
        attempt_id=row["id"],
        prospect_id=row["prospect_id"],
        phone_e164=row["phone_e164"],
        status=row["status"],
        requested_at=from_iso(row["requested_at"]),  # type: ignore[arg-type]
        dialed_at=from_iso(row["dialed_at"]),
    )


def attempts_for_policy(
    connection: sqlite3.Connection, *, prospect_id: str, phone_e164: str
) -> tuple[AttemptRecord, ...]:
    """Attempts the pre-dial engine needs to see.

    Attempt limits count against the number and the in-flight guard is scoped to
    the prospect (SPEC 4.2), so both sets are fetched.
    """
    rows = connection.execute(
        "SELECT * FROM call_attempt WHERE phone_e164 = ? OR prospect_id = ? ORDER BY requested_at",
        (_require_e164(phone_e164), prospect_id),
    ).fetchall()
    return tuple(_attempt_from_row(row) for row in rows)


def attempts_for_prospect(
    connection: sqlite3.Connection, prospect_id: str
) -> tuple[AttemptRecord, ...]:
    rows = connection.execute(
        "SELECT * FROM call_attempt WHERE prospect_id = ? ORDER BY requested_at DESC",
        (prospect_id,),
    ).fetchall()
    return tuple(_attempt_from_row(row) for row in rows)


# --- outcomes --------------------------------------------------------------


def insert_call_outcome(
    connection: sqlite3.Connection,
    *,
    call_attempt_id: str,
    transcript: dict,
    transcript_source: str,
    disclosure_ok: bool,
    violations: list[dict],
    interest: str,
    meeting_requested: bool,
    opt_out_requested: bool,
    extraction_method: str,
    processed_at: datetime,
    has_news: bool | None = None,
    news_summary: str | None = None,
    meeting_preferences: str | None = None,
) -> str:
    identifier = next_id(connection, "out")
    connection.execute(
        "INSERT INTO call_outcome (id, call_attempt_id, transcript_json, transcript_source,"
        " disclosure_ok, violations_json, has_news, news_summary, interest, meeting_requested,"
        " meeting_preferences, opt_out_requested, extraction_method, processed_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            identifier,
            call_attempt_id,
            json.dumps(transcript),
            transcript_source,
            1 if disclosure_ok else 0,
            json.dumps(violations),
            None if has_news is None else int(has_news),
            news_summary,
            interest,
            1 if meeting_requested else 0,
            meeting_preferences,
            1 if opt_out_requested else 0,
            extraction_method,
            to_iso(processed_at),
        ),
    )
    return identifier


def get_outcome_for_attempt(connection: sqlite3.Connection, attempt_id: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM call_outcome WHERE call_attempt_id = ?", (attempt_id,)
    ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["transcript"] = json.loads(record.pop("transcript_json"))
    record["violations"] = json.loads(record.pop("violations_json"))
    record["disclosure_ok"] = bool(record["disclosure_ok"])
    record["meeting_requested"] = bool(record["meeting_requested"])
    record["opt_out_requested"] = bool(record["opt_out_requested"])
    return record


# --- the seam --------------------------------------------------------------


def build_pre_dial_request(
    connection: sqlite3.Connection, prospect_id: str, now: datetime
) -> PreDialRequest:
    """Assemble everything the pure engine needs. The engine fetches nothing."""
    prospect = get_prospect(connection, prospect_id)
    if prospect is None:
        raise StorageError(f"no such prospect: {prospect_id}")

    return PreDialRequest(
        prospect=prospect.to_policy(),
        now=now,
        consent=get_consent(connection, prospect_id),
        suppression=tuple(list_suppressions(connection)),
        attempts=attempts_for_policy(
            connection, prospect_id=prospect_id, phone_e164=prospect.phone_e164
        ),
    )


def get_attempt(connection: sqlite3.Connection, attempt_id: str) -> dict | None:
    row = connection.execute("SELECT * FROM call_attempt WHERE id = ?", (attempt_id,)).fetchone()
    return dict(row) if row else None


def find_attempt_by_conversation(
    connection: sqlite3.Connection, conversation_id: str
) -> dict | None:
    row = connection.execute(
        "SELECT * FROM call_attempt WHERE provider_conversation_id = ?", (conversation_id,)
    ).fetchone()
    return dict(row) if row else None


def latest_attempt(connection: sqlite3.Connection, prospect_id: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM call_attempt WHERE prospect_id = ?"
        " ORDER BY requested_at DESC, id DESC LIMIT 1",
        (prospect_id,),
    ).fetchone()
    return dict(row) if row else None


def latest_evaluation(connection: sqlite3.Connection, prospect_id: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM policy_evaluation WHERE prospect_id = ?"
        " ORDER BY evaluated_at DESC, id DESC LIMIT 1",
        (prospect_id,),
    ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["decision_object"] = json.loads(record.pop("checks_json"))
    return record


def latest_outcome(connection: sqlite3.Connection, prospect_id: str) -> dict | None:
    """The most recent outcome for a prospect, across all their attempts.

    Not the same as "the outcome of the latest attempt": the latest attempt is
    often a block, which never produces an outcome, and the last thing that
    actually happened on the phone is still worth showing.
    """
    row = connection.execute(
        "SELECT o.call_attempt_id FROM call_outcome o"
        " JOIN call_attempt a ON a.id = o.call_attempt_id"
        " WHERE a.prospect_id = ? ORDER BY o.processed_at DESC, o.id DESC LIMIT 1",
        (prospect_id,),
    ).fetchone()
    return get_outcome_for_attempt(connection, row["call_attempt_id"]) if row else None
