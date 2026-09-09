"""Storage and the data model. SPEC 6.1, 6.2.

The test that matters most here is the last one: seed the database, run the
real policy engine over it, and assert that each seeded prospect blocks for the
reason it was seeded to demonstrate. That is the join between step 1 and step 2
of the build, and it is the thing most likely to rot silently.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

import pytest
from tests.conftest import AE_NUMBER, UK_NUMBER, at

from warmline.policy.engine import evaluate_pre_dial
from warmline.storage import repository
from warmline.storage.db import connect, from_iso, migrate, next_id, to_iso
from warmline.storage.repository import StorageError

NOW = at("2026-09-09T06:00:00Z")  # Wednesday, 10:00 in Dubai: inside AE hours


@pytest.fixture
def db():
    connection = connect()
    migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def prospect(db):
    return repository.insert_prospect(
        db,
        full_name="Layla Haddad",
        company="Northwind Robotics",
        phone_e164=AE_NUMBER,
        timezone="Asia/Dubai",
        region_profile="AE",
        now=NOW,
    )


# --- migrations ------------------------------------------------------------


def test_migration_creates_the_documented_tables(db):
    tables = {
        row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert {
        "prospect",
        "consent",
        "suppression_entry",
        "policy_evaluation",
        "call_attempt",
        "call_outcome",
    } <= tables


def test_migration_is_idempotent(db):
    assert migrate(db) == []


def test_migration_records_what_it_applied():
    connection = connect()

    assert migrate(connection) == ["001_initial"]
    assert connection.execute("SELECT version FROM schema_migration").fetchone()[0] == "001_initial"


def test_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO consent (id, prospect_id, lawful_basis, captured_at, evidence, created_at)"
            " VALUES ('con_x', 'psp_nope', 'explicit_opt_in', ?, 'x', ?)",
            (to_iso(NOW), to_iso(NOW)),
        )


# --- ids and timestamps ----------------------------------------------------


def test_ids_are_sequential_and_prefixed(db):
    assert [next_id(db, "att") for _ in range(3)] == ["att_0001", "att_0002", "att_0003"]


def test_id_counters_are_independent_per_prefix(db):
    next_id(db, "att")
    assert next_id(db, "psp") == "psp_0001"


def test_timestamps_round_trip_as_utc(db):
    assert from_iso(to_iso(NOW)) == NOW


def test_naive_timestamps_are_stored_as_utc():
    naive = NOW.replace(tzinfo=None)
    assert to_iso(naive) == to_iso(NOW)


# --- prospects -------------------------------------------------------------


def test_prospect_round_trips(db, prospect):
    stored = repository.get_prospect(db, prospect.id)

    assert stored == prospect
    assert stored.is_fixture is True


def test_a_prospect_number_is_normalised_on_write(db):
    """SPEC 6.1: one normalisation function, used everywhere."""
    stored = repository.insert_prospect(
        db,
        full_name="Omar Farouk",
        company="Cedarpoint Analytics",
        phone_e164="+971 50 123 4567",
        timezone="Asia/Dubai",
        region_profile="AE",
        now=NOW,
    )

    assert stored.phone_e164 == AE_NUMBER


def test_an_invalid_number_is_refused_rather_than_stored(db):
    with pytest.raises(StorageError):
        repository.insert_prospect(
            db,
            full_name="Nobody",
            company="Nowhere",
            phone_e164="12345",
            timezone="Asia/Dubai",
            region_profile="AE",
            now=NOW,
        )


def test_the_policy_projection_carries_only_what_the_engine_needs(db, prospect):
    projected = prospect.to_policy()

    assert projected.id == prospect.id
    assert projected.phone_e164 == prospect.phone_e164
    assert not hasattr(projected, "full_name")


# --- consent ---------------------------------------------------------------


def test_consent_round_trips_including_its_nulls(db, prospect):
    repository.insert_consent(
        db,
        prospect_id=prospect.id,
        lawful_basis="explicit_opt_in",
        captured_at=NOW - timedelta(days=10),
        evidence="fictional seed record",
        now=NOW,
    )

    consent = repository.get_consent(db, prospect.id)
    assert consent.lawful_basis == "explicit_opt_in"
    assert consent.expires_at is None
    assert consent.withdrawn_at is None


def test_the_most_recent_consent_record_wins(db, prospect):
    for days, basis in ((100, "explicit_opt_in"), (10, "existing_client")):
        repository.insert_consent(
            db,
            prospect_id=prospect.id,
            lawful_basis=basis,
            captured_at=NOW - timedelta(days=days),
            evidence="fictional",
            now=NOW,
        )

    assert repository.get_consent(db, prospect.id).lawful_basis == "existing_client"


def test_withdrawal_stamps_the_existing_record(db, prospect):
    """Withdrawal is permanent, so it marks the row rather than adding one."""
    repository.insert_consent(
        db,
        prospect_id=prospect.id,
        lawful_basis="explicit_opt_in",
        captured_at=NOW - timedelta(days=10),
        evidence="fictional",
        now=NOW,
    )

    repository.withdraw_consent(db, prospect.id, when=NOW)

    assert repository.get_consent(db, prospect.id).withdrawn_at == NOW
    assert db.execute("SELECT COUNT(*) FROM consent").fetchone()[0] == 1


# --- suppression -----------------------------------------------------------


def test_suppression_is_stored_normalised(db):
    repository.add_suppression(
        db, phone_e164="+971 50 123 4567", reason="do_not_call", source="seed", now=NOW
    )

    assert repository.list_suppressions(db)[0].phone_e164 == AE_NUMBER


def test_suppressing_a_number_twice_is_not_an_error(db):
    first = repository.add_suppression(
        db, phone_e164=AE_NUMBER, reason="do_not_call", source="seed", now=NOW
    )
    second = repository.add_suppression(
        db, phone_e164=AE_NUMBER, reason="complaint", source="api", now=NOW
    )

    assert first is not None
    assert second is None
    assert len(repository.list_suppressions(db)) == 1


# --- evaluations and attempts ----------------------------------------------


def test_a_policy_decision_is_stored_verbatim(db, prospect):
    """SPEC 6.2: the UI, the tests and the audit trail read the same bytes."""
    from warmline.config import load_policy_config

    decision = evaluate_pre_dial(
        repository.build_pre_dial_request(db, prospect.id, NOW), load_policy_config()
    )
    evaluation_id = repository.insert_policy_evaluation(db, decision)

    assert repository.get_policy_evaluation(db, evaluation_id) == json.loads(
        json.dumps(decision.to_dict())
    )


def test_a_blocked_attempt_is_recorded_with_no_dial_time(db, prospect):
    """A block is a record, not the absence of one (SPEC 6.2)."""
    from warmline.config import load_policy_config

    decision = evaluate_pre_dial(
        repository.build_pre_dial_request(db, prospect.id, NOW), load_policy_config()
    )
    evaluation_id = repository.insert_policy_evaluation(db, decision)

    attempt_id = repository.insert_call_attempt(
        db,
        prospect_id=prospect.id,
        phone_e164=prospect.phone_e164,
        status="blocked",
        policy_evaluation_id=evaluation_id,
        provider="simulated",
        requested_at=NOW,
    )

    row = db.execute("SELECT * FROM call_attempt WHERE id = ?", (attempt_id,)).fetchone()
    assert row["status"] == "blocked"
    assert row["dialed_at"] is None
    assert row["policy_evaluation_id"] == evaluation_id


def test_an_attempt_needs_a_status_the_schema_recognises(db, prospect):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO call_attempt (id, prospect_id, phone_e164, status,"
            " policy_evaluation_id, provider, requested_at)"
            " VALUES ('att_x', ?, ?, 'exploded', 'pev_x', 'simulated', ?)",
            (prospect.id, prospect.phone_e164, to_iso(NOW)),
        )


def test_updating_an_unknown_attempt_field_is_refused(db):
    with pytest.raises(StorageError):
        repository.update_call_attempt(db, "att_0001", nonsense="x")


# --- the seam --------------------------------------------------------------


def test_build_pre_dial_request_assembles_what_the_engine_needs(db, prospect):
    repository.insert_consent(
        db,
        prospect_id=prospect.id,
        lawful_basis="explicit_opt_in",
        captured_at=NOW - timedelta(days=10),
        evidence="fictional",
        now=NOW,
    )
    repository.add_suppression(
        db, phone_e164=UK_NUMBER, reason="do_not_call", source="seed", now=NOW
    )

    request = repository.build_pre_dial_request(db, prospect.id, NOW)

    assert request.prospect.id == prospect.id
    assert request.now == NOW
    assert request.consent.lawful_basis == "explicit_opt_in"
    assert len(request.suppression) == 1
    assert request.attempts == ()


def test_build_pre_dial_request_rejects_an_unknown_prospect(db):
    with pytest.raises(StorageError):
        repository.build_pre_dial_request(db, "psp_nope", NOW)


# --- outcomes --------------------------------------------------------------


def _completed_attempt(db, prospect):
    from warmline.config import load_policy_config

    decision = evaluate_pre_dial(
        repository.build_pre_dial_request(db, prospect.id, NOW), load_policy_config()
    )
    evaluation_id = repository.insert_policy_evaluation(db, decision)
    return repository.insert_call_attempt(
        db,
        prospect_id=prospect.id,
        phone_e164=prospect.phone_e164,
        status="completed",
        policy_evaluation_id=evaluation_id,
        provider="simulated",
        scenario="compliant_meeting_booked",
        requested_at=NOW,
        dialed_at=NOW,
    )


TRANSCRIPT = {
    "conversation_id": "sim_compliant_001",
    "source": "scenario",
    "turns": [{"index": 0, "role": "agent", "text": "Hi, I'm an AI assistant."}],
}


def test_an_outcome_round_trips_with_its_transcript(db, prospect):
    attempt_id = _completed_attempt(db, prospect)

    repository.insert_call_outcome(
        db,
        call_attempt_id=attempt_id,
        transcript=TRANSCRIPT,
        transcript_source="scenario",
        disclosure_ok=True,
        violations=[],
        interest="interested",
        meeting_requested=True,
        opt_out_requested=False,
        extraction_method="deterministic",
        processed_at=NOW,
        has_news=True,
        news_summary="Series A closing next month.",
    )

    outcome = repository.get_outcome_for_attempt(db, attempt_id)
    assert outcome["transcript"] == TRANSCRIPT
    assert outcome["violations"] == []
    assert outcome["disclosure_ok"] is True
    assert outcome["meeting_requested"] is True
    assert outcome["review_status"] == "unreviewed"


def test_a_transcript_source_outside_the_two_allowed_values_is_refused(db, prospect):
    """No scripted conversation can be labelled as anything but a scenario."""
    attempt_id = _completed_attempt(db, prospect)

    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_call_outcome(
            db,
            call_attempt_id=attempt_id,
            transcript=TRANSCRIPT,
            transcript_source="real",
            disclosure_ok=True,
            violations=[],
            interest="interested",
            meeting_requested=False,
            opt_out_requested=False,
            extraction_method="deterministic",
            processed_at=NOW,
        )


def test_an_attempt_can_only_have_one_outcome(db, prospect):
    """A provider retry must not be able to produce two outcomes (SPEC 9.1)."""
    attempt_id = _completed_attempt(db, prospect)
    kwargs = dict(
        call_attempt_id=attempt_id,
        transcript=TRANSCRIPT,
        transcript_source="scenario",
        disclosure_ok=True,
        violations=[],
        interest="unclear",
        meeting_requested=False,
        opt_out_requested=False,
        extraction_method="deterministic",
        processed_at=NOW,
    )
    repository.insert_call_outcome(db, **kwargs)

    with pytest.raises(sqlite3.IntegrityError):
        repository.insert_call_outcome(db, **kwargs)
