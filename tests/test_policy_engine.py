"""Pre-dial policy engine. SPEC 4.1, 4.2, 4.3; test list from SPEC 9.1.

Written before the implementation. Every case in the spec's list is a named
test here, plus the boundary cases the spec calls out as the place where the
implementation and the tests are most likely to disagree silently.
"""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest

from tests.conftest import (
    AE_NUMBER,
    UK_NUMBER,
    UNVERIFIED_NUMBER,
    US_LA_NUMBER,
    at,
    blocked_attempt,
    check,
    dialed,
    make_prospect,
    make_request,
    valid_consent,
    with_config,
)
from warmline.policy import codes
from warmline.policy.engine import evaluate_pre_dial
from warmline.policy.models import Consent, SuppressionEntry

# 2026-09-09 is a Wednesday, a permitted day under every profile.
# 16:00Z is 20:00 in Dubai, 17:00 in London (BST) and 09:00 in Los Angeles (PDT).
WEDNESDAY_1600Z = "2026-09-09T16:00:00Z"
# 10:00 in Dubai: comfortably inside the AE window.
WEDNESDAY_0600Z = "2026-09-09T06:00:00Z"


# --- the all-clear case ----------------------------------------------------


def test_all_clear_allows_and_every_check_passes(config):
    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z)), config)

    assert decision.decision == "allow"
    assert decision.primary_reason is None
    assert decision.blocking_reasons == ()
    assert [c.result for c in decision.checks] == ["pass"] * len(decision.checks)


def test_all_nine_checks_are_evaluated(config):
    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z)), config)

    assert {c.code for c in decision.checks} == {
        codes.NUMBER_NOT_VERIFIED,
        codes.CONSENT_MISSING,
        codes.CONSENT_EXPIRED,
        codes.CONSENT_WITHDRAWN,
        codes.NUMBER_SUPPRESSED,
        codes.TIMEZONE_PREFIX_MISMATCH,
        codes.OUTSIDE_CALLING_HOURS,
        codes.ATTEMPT_LIMIT_REACHED,
        codes.CALL_IN_FLIGHT,
    }


# --- consent ---------------------------------------------------------------


def test_missing_consent_blocks(config):
    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), consent=None), config)

    assert decision.decision == "block"
    assert codes.CONSENT_MISSING in decision.blocking_reasons
    assert check(decision, codes.CONSENT_MISSING).recoverable == "on_data_fix"


def test_consent_expired_exactly_at_expiry_blocks(config):
    now = at(WEDNESDAY_0600Z)
    consent = Consent(
        lawful_basis="explicit_opt_in",
        captured_at=now - timedelta(days=180),
        expires_at=now,
    )

    decision = evaluate_pre_dial(make_request(now=now, consent=consent), config)

    assert codes.CONSENT_EXPIRED in decision.blocking_reasons


def test_consent_expired_one_second_later_blocks(config):
    now = at(WEDNESDAY_0600Z)
    consent = Consent(
        lawful_basis="explicit_opt_in",
        captured_at=now - timedelta(days=180),
        expires_at=now - timedelta(seconds=1),
    )

    decision = evaluate_pre_dial(make_request(now=now, consent=consent), config)

    assert codes.CONSENT_EXPIRED in decision.blocking_reasons


def test_consent_one_second_before_expiry_is_still_valid(config):
    now = at(WEDNESDAY_0600Z)
    consent = Consent(
        lawful_basis="explicit_opt_in",
        captured_at=now - timedelta(days=180),
        expires_at=now + timedelta(seconds=1),
    )

    decision = evaluate_pre_dial(make_request(now=now, consent=consent), config)

    assert decision.decision == "allow"


def test_consent_without_expiry_does_not_expire(config):
    now = at(WEDNESDAY_0600Z)
    consent = Consent(lawful_basis="existing_client", captured_at=now - timedelta(days=900))

    decision = evaluate_pre_dial(make_request(now=now, consent=consent), config)

    assert decision.decision == "allow"


def test_withdrawn_consent_blocks_and_is_never_recoverable(config):
    now = at(WEDNESDAY_0600Z)
    consent = Consent(
        lawful_basis="explicit_opt_in",
        captured_at=now - timedelta(days=10),
        withdrawn_at=now - timedelta(days=1),
    )

    decision = evaluate_pre_dial(make_request(now=now, consent=consent), config)

    assert codes.CONSENT_WITHDRAWN in decision.blocking_reasons
    assert check(decision, codes.CONSENT_WITHDRAWN).recoverable == "never"


# --- suppression -----------------------------------------------------------


def test_suppressed_number_blocks(config):
    entry = SuppressionEntry(phone_e164=AE_NUMBER, reason="do_not_call", source="seed")

    decision = evaluate_pre_dial(
        make_request(now=at(WEDNESDAY_0600Z), suppression=(entry,)), config
    )

    assert codes.NUMBER_SUPPRESSED in decision.blocking_reasons
    assert check(decision, codes.NUMBER_SUPPRESSED).recoverable == "never"


def test_suppression_matches_a_differently_formatted_number(config):
    """`+971 50 123 4567` and `+971501234567` are the same number (SPEC 4.2)."""
    entry = SuppressionEntry(phone_e164="+971 50 123 4567", reason="complaint")

    decision = evaluate_pre_dial(
        make_request(now=at(WEDNESDAY_0600Z), suppression=(entry,)), config
    )

    assert codes.NUMBER_SUPPRESSED in decision.blocking_reasons


def test_suppression_detail_echoes_the_reason(config):
    """So the UI can say *why* without a second lookup (SPEC 4.2)."""
    entry = SuppressionEntry(phone_e164=AE_NUMBER, reason="opt_out_in_call", source="post_call")

    decision = evaluate_pre_dial(
        make_request(now=at(WEDNESDAY_0600Z), suppression=(entry,)), config
    )

    detail = check(decision, codes.NUMBER_SUPPRESSED).detail
    assert detail["suppression_reason"] == "opt_out_in_call"
    assert detail["source"] == "post_call"


def test_a_different_suppressed_number_does_not_block(config):
    entry = SuppressionEntry(phone_e164=UK_NUMBER, reason="do_not_call")

    decision = evaluate_pre_dial(
        make_request(now=at(WEDNESDAY_0600Z), suppression=(entry,)), config
    )

    assert decision.decision == "allow"


# --- calling hours ---------------------------------------------------------


def test_same_instant_is_blocked_in_dubai_and_allowed_in_london(config):
    """The point of storing a timezone per prospect, in one assertion."""
    now = at(WEDNESDAY_1600Z)

    dubai = evaluate_pre_dial(make_request(now=now), config)
    london = evaluate_pre_dial(
        make_request(
            now=now,
            prospect=make_prospect(
                phone_e164=UK_NUMBER, tz="Europe/London", region_profile="UK"
            ),
        ),
        config,
    )

    assert codes.OUTSIDE_CALLING_HOURS in dubai.blocking_reasons  # 20:00 local
    assert london.decision == "allow"  # 17:00 local


def test_same_instant_is_allowed_in_los_angeles(config):
    """09:00 PDT, exactly at the US window start."""
    decision = evaluate_pre_dial(
        make_request(
            now=at(WEDNESDAY_1600Z),
            prospect=make_prospect(
                phone_e164=US_LA_NUMBER, tz="America/Los_Angeles", region_profile="US"
            ),
        ),
        config,
    )

    assert decision.decision == "allow"


@pytest.mark.parametrize(
    ("instant", "expected", "why"),
    [
        ("2026-09-09T05:00:00Z", "allow", "09:00:00 local, exactly at the window start"),
        ("2026-09-09T04:59:59Z", "block", "08:59:59 local, one second before the start"),
        ("2026-09-09T13:59:59Z", "allow", "17:59:59 local, one second before the end"),
        ("2026-09-09T14:00:00Z", "block", "18:00:00 local, exactly at the window end"),
    ],
)
def test_window_boundaries_are_half_open(config, instant, expected, why):
    """[start, end): open at the start, closed at the end. SPEC 4.2."""
    decision = evaluate_pre_dial(make_request(now=at(instant)), config)

    assert decision.decision == expected, why


def test_non_permitted_local_day_blocks(config):
    """Friday is outside the AE profile's days."""
    decision = evaluate_pre_dial(make_request(now=at("2026-09-11T08:00:00Z")), config)

    outcome = check(decision, codes.OUTSIDE_CALLING_HOURS)
    assert outcome.result == "block"
    assert outcome.detail["local_day"] == "fri"


def test_dst_moves_the_same_utc_time_across_the_london_window_edge(config):
    """08:59Z is 08:59 GMT in March and 09:59 BST in April. One blocks, one does not.

    UK and US clock changes both fall on a Sunday, which is never a permitted
    calling day, so a test *on* the transition day would only ever assert the
    day-of-week rule. This asserts the property that actually matters.
    """
    london = make_prospect(phone_e164=UK_NUMBER, tz="Europe/London", region_profile="UK")

    in_gmt = evaluate_pre_dial(make_request(now=at("2026-03-25T08:59:00Z"), prospect=london), config)
    in_bst = evaluate_pre_dial(make_request(now=at("2026-04-01T08:59:00Z"), prospect=london), config)

    assert codes.OUTSIDE_CALLING_HOURS in in_gmt.blocking_reasons
    assert in_bst.decision == "allow"


def test_dst_moves_the_same_utc_time_across_the_los_angeles_window_edge(config):
    """16:30Z is 08:30 PST in early March and 09:30 PDT a week later."""
    la = make_prospect(phone_e164=US_LA_NUMBER, tz="America/Los_Angeles", region_profile="US")

    in_pst = evaluate_pre_dial(make_request(now=at("2026-03-04T16:30:00Z"), prospect=la), config)
    in_pdt = evaluate_pre_dial(make_request(now=at("2026-03-11T16:30:00Z"), prospect=la), config)

    assert codes.OUTSIDE_CALLING_HOURS in in_pst.blocking_reasons
    assert in_pdt.decision == "allow"


def test_out_of_hours_reports_when_it_would_pass(config):
    """Before the window opens: today at 09:00 local, which is 05:00Z."""
    decision = evaluate_pre_dial(make_request(now=at("2026-09-09T04:00:00Z")), config)

    outcome = check(decision, codes.OUTSIDE_CALLING_HOURS)
    assert outcome.recoverable == "after"
    assert outcome.retry_after == at("2026-09-09T05:00:00Z")


def test_retry_after_skips_a_non_permitted_day(config):
    """After Thursday's window closes, the next AE opening is Sunday."""
    decision = evaluate_pre_dial(make_request(now=at("2026-09-10T15:00:00Z")), config)

    outcome = check(decision, codes.OUTSIDE_CALLING_HOURS)
    assert outcome.retry_after == at("2026-09-13T05:00:00Z")


def test_out_of_hours_message_does_not_leak_the_number(config):
    """SPEC 4.3: `message` is safe to show in a UI."""
    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_1600Z)), config)

    for outcome in decision.checks:
        assert AE_NUMBER not in (outcome.message or "")


# --- timezone / prefix mismatch --------------------------------------------


def test_timezone_prefix_mismatch_blocks(config):
    """A +1 number carrying Asia/Dubai defeats the hours check silently."""
    prospect = make_prospect(phone_e164=US_LA_NUMBER, tz="Asia/Dubai", region_profile="AE")

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), config)

    assert codes.TIMEZONE_PREFIX_MISMATCH in decision.blocking_reasons
    detail = check(decision, codes.TIMEZONE_PREFIX_MISMATCH).detail
    assert detail["number_country"] == "US"
    assert detail["timezone_countries"] == ["AE"]


def test_timezone_prefix_mismatch_warns_when_configured(config):
    """Both settings are supported and both are tested (SPEC 4.2)."""
    warn_config = with_config(config, timezone_mismatch_action="warn")
    prospect = make_prospect(phone_e164=US_LA_NUMBER, tz="Asia/Dubai", region_profile="AE")

    decision = evaluate_pre_dial(
        make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), warn_config
    )

    assert check(decision, codes.TIMEZONE_PREFIX_MISMATCH).result == "warn"
    assert codes.TIMEZONE_PREFIX_MISMATCH not in decision.blocking_reasons
    assert decision.decision == "allow"


def test_matching_timezone_and_prefix_passes(config):
    prospect = make_prospect(phone_e164=UK_NUMBER, tz="Europe/London", region_profile="UK")

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_1600Z), prospect=prospect), config)

    assert check(decision, codes.TIMEZONE_PREFIX_MISMATCH).result == "pass"


# --- attempt limits --------------------------------------------------------


def test_one_attempt_in_the_last_24h_reaches_the_limit(config):
    now = at(WEDNESDAY_0600Z)
    attempts = (dialed(now - timedelta(hours=2)),)

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    assert codes.ATTEMPT_LIMIT_REACHED in decision.blocking_reasons
    detail = check(decision, codes.ATTEMPT_LIMIT_REACHED).detail
    assert detail["attempts_24h"] == 1
    assert detail["limit_24h"] == 1


def test_an_attempt_just_outside_the_24h_window_does_not_count(config):
    now = at(WEDNESDAY_0600Z)
    attempts = (dialed(now - timedelta(hours=24, seconds=1)),)

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    assert decision.decision == "allow"


def test_an_attempt_exactly_24h_ago_is_outside_the_window(config):
    """The window is the last 24 hours, not the last 24 hours inclusive."""
    now = at(WEDNESDAY_0600Z)
    attempts = (dialed(now - timedelta(hours=24)),)

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    assert decision.decision == "allow"


def test_three_attempts_in_seven_days_reaches_the_weekly_limit(config):
    now = at(WEDNESDAY_0600Z)
    attempts = (
        dialed(now - timedelta(days=2)),
        dialed(now - timedelta(days=4)),
        dialed(now - timedelta(days=6)),
    )

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    detail = check(decision, codes.ATTEMPT_LIMIT_REACHED).detail
    assert detail["attempts_7d"] == 3
    assert detail["limit_7d"] == 3
    assert codes.ATTEMPT_LIMIT_REACHED in decision.blocking_reasons


def test_two_attempts_in_seven_days_is_one_under_the_weekly_limit(config):
    now = at(WEDNESDAY_0600Z)
    attempts = (dialed(now - timedelta(days=2)), dialed(now - timedelta(days=4)))

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    assert decision.decision == "allow"


def test_a_blocked_attempt_does_not_consume_budget(config):
    """Only calls that reached a provider count (SPEC 4.2)."""
    now = at(WEDNESDAY_0600Z)
    attempts = (
        blocked_attempt(now - timedelta(minutes=5)),
        blocked_attempt(now - timedelta(minutes=4)),
        blocked_attempt(now - timedelta(minutes=3)),
    )

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    assert decision.decision == "allow"


def test_attempts_are_counted_against_the_number_not_the_prospect(config):
    """Two prospect rows sharing a number cannot double the budget (SPEC 4.2)."""
    now = at(WEDNESDAY_0600Z)
    attempts = (dialed(now - timedelta(hours=2), prospect_id="psp_9999"),)

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    assert codes.ATTEMPT_LIMIT_REACHED in decision.blocking_reasons


def test_attempt_limit_reports_when_it_would_pass(config):
    now = at(WEDNESDAY_0600Z)
    last = now - timedelta(hours=2)

    decision = evaluate_pre_dial(make_request(now=now, attempts=(dialed(last),)), config)

    assert check(decision, codes.ATTEMPT_LIMIT_REACHED).retry_after == last + timedelta(hours=24)


# --- verified numbers ------------------------------------------------------


def test_unverified_number_blocks(config):
    prospect = make_prospect(phone_e164=UNVERIFIED_NUMBER)

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), config)

    assert codes.NUMBER_NOT_VERIFIED in decision.blocking_reasons
    assert check(decision, codes.NUMBER_NOT_VERIFIED).recoverable == "never"


def test_unverified_number_outranks_every_other_reason(config):
    """A run against an accidental real list must block on the right reason."""
    prospect = make_prospect(phone_e164=UNVERIFIED_NUMBER)

    decision = evaluate_pre_dial(
        make_request(now=at(WEDNESDAY_1600Z), prospect=prospect, consent=None), config
    )

    assert decision.primary_reason == codes.NUMBER_NOT_VERIFIED


# --- call in flight --------------------------------------------------------


@pytest.mark.parametrize("status", ["dialing", "in_progress"])
def test_a_call_in_flight_blocks(config, status):
    now = at(WEDNESDAY_0600Z)
    attempts = (dialed(now - timedelta(seconds=30), status=status),)

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    assert codes.CALL_IN_FLIGHT in decision.blocking_reasons


def test_a_finished_call_is_not_in_flight(config):
    now = at(WEDNESDAY_0600Z)
    attempts = (dialed(now - timedelta(days=3), status="completed"),)

    decision = evaluate_pre_dial(make_request(now=now, attempts=attempts), config)

    assert check(decision, codes.CALL_IN_FLIGHT).result == "pass"


def test_in_flight_is_scoped_to_the_prospect(config):
    now = at(WEDNESDAY_0600Z)
    other = dialed(
        now - timedelta(seconds=30),
        prospect_id="psp_9999",
        phone_e164=UK_NUMBER,
        status="dialing",
    )

    decision = evaluate_pre_dial(make_request(now=now, attempts=(other,)), config)

    assert check(decision, codes.CALL_IN_FLIGHT).result == "pass"


# --- severity and completeness ---------------------------------------------


def test_every_failure_is_reported_not_just_the_first(config):
    """Someone who fixes one block should not discover the others one at a time."""
    now = at(WEDNESDAY_1600Z)  # outside AE hours
    entry = SuppressionEntry(phone_e164=AE_NUMBER, reason="complaint")

    decision = evaluate_pre_dial(
        make_request(now=now, consent=None, suppression=(entry,)), config
    )

    assert set(decision.blocking_reasons) == {
        codes.CONSENT_MISSING,
        codes.NUMBER_SUPPRESSED,
        codes.OUTSIDE_CALLING_HOURS,
    }


def test_primary_reason_is_the_most_severe_block(config):
    now = at(WEDNESDAY_1600Z)
    entry = SuppressionEntry(phone_e164=AE_NUMBER, reason="complaint")

    decision = evaluate_pre_dial(
        make_request(now=now, consent=None, suppression=(entry,)), config
    )

    assert decision.primary_reason == codes.NUMBER_SUPPRESSED


def test_blocking_reasons_follow_severity_order(config):
    now = at(WEDNESDAY_1600Z)
    entry = SuppressionEntry(phone_e164=AE_NUMBER, reason="complaint")

    decision = evaluate_pre_dial(
        make_request(now=now, consent=None, suppression=(entry,)), config
    )

    ranks = [codes.SEVERITY_ORDER.index(reason) for reason in decision.blocking_reasons]
    assert ranks == sorted(ranks)


# --- malformed input: total, and fails closed ------------------------------


def test_malformed_number_is_not_evaluable_and_blocks(config):
    prospect = make_prospect(phone_e164="12345")

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), config)

    assert decision.decision == "block"
    assert codes.CHECK_NOT_EVALUABLE in decision.blocking_reasons


def test_unknown_timezone_is_not_evaluable_and_blocks(config):
    prospect = make_prospect(tz="Mars/Olympus")

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), config)

    assert decision.decision == "block"
    assert codes.CHECK_NOT_EVALUABLE in decision.blocking_reasons


def test_unlisted_timezone_is_not_silently_trusted(config):
    """A real timezone the policy config does not map to a country fails closed."""
    prospect = make_prospect(phone_e164=AE_NUMBER, tz="Australia/Sydney", region_profile="AE")

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), config)

    assert decision.decision == "block"
    assert codes.CHECK_NOT_EVALUABLE in decision.blocking_reasons


def test_missing_region_profile_is_not_evaluable_and_blocks(config):
    prospect = make_prospect(region_profile="ZZ")

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), config)

    assert decision.decision == "block"
    assert codes.CHECK_NOT_EVALUABLE in decision.blocking_reasons


def test_not_evaluable_names_the_check_that_could_not_run(config):
    prospect = make_prospect(region_profile="ZZ")

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), config)

    outcome = check(decision, codes.CHECK_NOT_EVALUABLE)
    assert outcome.detail["check"] == codes.OUTSIDE_CALLING_HOURS


@pytest.mark.parametrize(
    "prospect",
    [
        make_prospect(phone_e164=""),
        make_prospect(phone_e164="not a number"),
        make_prospect(phone_e164="+9999999999999999"),
        make_prospect(tz=""),
        make_prospect(tz="Mars/Olympus"),
        make_prospect(region_profile=""),
        make_prospect(phone_e164="12345", tz="Mars/Olympus", region_profile="ZZ"),
    ],
    ids=[
        "empty-number",
        "junk-number",
        "impossible-number",
        "empty-timezone",
        "unknown-timezone",
        "empty-profile",
        "everything-wrong",
    ],
)
def test_the_engine_is_total_and_never_raises(config, prospect):
    """Bad data is a block reason, not an exception (SPEC 4.1)."""
    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_0600Z), prospect=prospect), config)

    assert decision.decision == "block"


# --- the invariant ---------------------------------------------------------


def test_never_allows_when_any_check_blocks(config):
    """Fail closed, over every combination of the five easily-toggled failures."""
    now = at(WEDNESDAY_0600Z)
    out_of_hours = at(WEDNESDAY_1600Z)

    for no_consent, suppressed, unverified, late, at_limit in itertools.product(
        [False, True], repeat=5
    ):
        prospect = make_prospect(phone_e164=UNVERIFIED_NUMBER if unverified else AE_NUMBER)
        request = make_request(
            now=out_of_hours if late else now,
            prospect=prospect,
            consent=None if no_consent else valid_consent(now),
            suppression=(
                (SuppressionEntry(phone_e164=prospect.phone_e164, reason="manual"),)
                if suppressed
                else ()
            ),
            attempts=(dialed(now - timedelta(hours=1), phone_e164=prospect.phone_e164),)
            if at_limit
            else (),
        )

        decision = evaluate_pre_dial(request, config)
        blocked = any(c.result == "block" for c in decision.checks)

        assert decision.allowed is not blocked
        assert bool(decision.blocking_reasons) is blocked


# --- the emitted shape -----------------------------------------------------


def test_decision_serialises_to_the_documented_shape(config):
    """SPEC 4.3. The UI, the tests and the audit trail read the same object."""
    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_1600Z)), config)
    payload = decision.to_dict()

    assert set(payload) == {
        "decision",
        "policy_version",
        "config_digest",
        "evaluated_at",
        "prospect_id",
        "phone_e164",
        "primary_reason",
        "blocking_reasons",
        "checks",
    }
    assert payload["decision"] == "block"
    assert payload["policy_version"] == "1.0.0"
    assert payload["config_digest"].startswith("sha256:")
    assert payload["evaluated_at"].endswith("Z")
    assert payload["primary_reason"] == codes.OUTSIDE_CALLING_HOURS

    hours = next(c for c in payload["checks"] if c["code"] == codes.OUTSIDE_CALLING_HOURS)
    assert hours["result"] == "block"
    assert hours["recoverable"] == "after"
    assert hours["detail"]["timezone"] == "Asia/Dubai"
    assert hours["detail"]["profile"] == "AE"
    assert hours["detail"]["window"] == {"start": "09:00", "end": "18:00"}
    assert hours["detail"]["permitted_days"] == ["sun", "mon", "tue", "wed", "thu"]


def test_decision_is_json_serialisable(config):
    import json

    decision = evaluate_pre_dial(make_request(now=at(WEDNESDAY_1600Z)), config)

    assert json.loads(json.dumps(decision.to_dict()))["decision"] == "block"
