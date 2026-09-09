"""Builders for policy-engine tests.

These tests run against the *shipped* policy config in `policy/`, not against a
toy config invented for the tests. If someone widens a calling window or raises
an attempt limit, these tests should notice.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from warmline.config import load_policy_config
from warmline.policy.models import (
    AttemptRecord,
    Consent,
    PolicyConfig,
    PreDialRequest,
    Prospect,
    SuppressionEntry,
)

# Every number here is fictional. UK numbers are from the Ofcom range reserved
# for drama; US numbers are from the 555-01xx fictional range. libphonenumber
# does not consider the Ofcom *mobile* drama range (+447700 900xxx) valid, so
# the reserved Leeds landline range is used instead.
AE_NUMBER = "+971501234567"
AE_NUMBER_2 = "+971501234568"
UK_NUMBER = "+441134960001"
US_LA_NUMBER = "+13105550123"
US_NY_NUMBER = "+12025550123"
UNVERIFIED_NUMBER = "+971501111111"


def at(value: str) -> datetime:
    """Parse an ISO-8601 instant, `Z` included, into an aware UTC datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@pytest.fixture(scope="session")
def config() -> PolicyConfig:
    return load_policy_config()


def with_config(config: PolicyConfig, **overrides) -> PolicyConfig:
    return dataclasses.replace(config, **overrides)


def make_prospect(
    *,
    prospect_id: str = "psp_0001",
    phone_e164: str = AE_NUMBER,
    tz: str = "Asia/Dubai",
    region_profile: str = "AE",
) -> Prospect:
    return Prospect(
        id=prospect_id,
        phone_e164=phone_e164,
        timezone=tz,
        region_profile=region_profile,
    )


def valid_consent(now: datetime) -> Consent:
    """Consent captured 30 days ago, expiring 150 days from now."""
    from datetime import timedelta

    return Consent(
        lawful_basis="test_number_owner_agreement",
        captured_at=now - timedelta(days=30),
        expires_at=now + timedelta(days=150),
        evidence="fictional seed record — no real person",
    )


def make_request(
    *,
    now: datetime,
    prospect: Prospect | None = None,
    consent: Consent | None = ...,  # type: ignore[assignment]
    suppression: tuple[SuppressionEntry, ...] = (),
    attempts: tuple[AttemptRecord, ...] = (),
) -> PreDialRequest:
    """A request that passes every check unless an argument says otherwise."""
    subject = prospect or make_prospect()
    return PreDialRequest(
        prospect=subject,
        now=now,
        consent=valid_consent(now) if consent is ... else consent,
        suppression=suppression,
        attempts=attempts,
    )


def dialed(
    when: datetime,
    *,
    phone_e164: str = AE_NUMBER,
    prospect_id: str = "psp_0001",
    status: str = "completed",
) -> AttemptRecord:
    """An attempt that reached a provider, and therefore consumes budget."""
    return AttemptRecord(
        attempt_id=f"att_{when.timestamp():.0f}",
        prospect_id=prospect_id,
        phone_e164=phone_e164,
        status=status,
        requested_at=when,
        dialed_at=when,
    )


def blocked_attempt(
    when: datetime,
    *,
    phone_e164: str = AE_NUMBER,
    prospect_id: str = "psp_0001",
) -> AttemptRecord:
    """An attempt policy stopped. Never reached a provider, so costs no budget."""
    return AttemptRecord(
        attempt_id=f"att_blocked_{when.timestamp():.0f}",
        prospect_id=prospect_id,
        phone_e164=phone_e164,
        status="blocked",
        requested_at=when,
        dialed_at=None,
    )


def check(decision, code: str):
    """The outcome for one check code, or None if the engine did not emit it."""
    for outcome in decision.checks:
        if outcome.code == code:
            return outcome
    return None
