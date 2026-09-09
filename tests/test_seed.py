"""Seed data. SPEC 2.1, SPEC 6.2.

The seed set exists so that five different pre-dial block reasons are visible
in the UI on first run rather than only in the test suite. These tests assert
that property, so that editing the seed data has to be a deliberate act.
"""

from __future__ import annotations

import pytest
from tests.conftest import at

from warmline.policy import codes
from warmline.policy.engine import evaluate_pre_dial
from warmline.storage import repository
from warmline.storage.db import connect, migrate
from warmline.storage.seed import SEED_PROSPECTS, seed

NOW = at("2026-09-09T06:00:00Z")  # Wednesday, 10:00 in Dubai: inside AE hours


@pytest.fixture
def db():
    connection = connect()
    migrate(connection)
    yield connection
    connection.close()


def test_seed_refuses_to_run_twice(db):
    seed(db, NOW)

    with pytest.raises(RuntimeError):
        seed(db, NOW)


def test_every_seeded_prospect_is_labelled_fictional(db):
    seed(db, NOW)

    assert all(record.is_fixture for record in repository.list_prospects(db))


def test_seeded_prospects_block_for_the_reason_they_demonstrate(db, config):
    """Step 1 and step 2, joined: real storage through the real engine."""
    seed(db, NOW)

    expected = {
        "psp_0001": None,
        "psp_0002": codes.CONSENT_EXPIRED,
        "psp_0003": codes.CONSENT_WITHDRAWN,
        "psp_0004": codes.NUMBER_SUPPRESSED,
        "psp_0005": codes.CONSENT_MISSING,
        "psp_0006": codes.NUMBER_NOT_VERIFIED,
    }

    actual = {
        record.id: evaluate_pre_dial(
            repository.build_pre_dial_request(db, record.id, NOW), config
        ).primary_reason
        for record in repository.list_prospects(db)
    }

    assert actual == expected


def test_the_seed_set_demonstrates_five_distinct_block_reasons(db, config):
    """If someone edits the seed data, this says what it was for."""
    seed(db, NOW)

    reasons = {
        evaluate_pre_dial(
            repository.build_pre_dial_request(db, record.id, NOW), config
        ).primary_reason
        for record in repository.list_prospects(db)
    }

    assert len(reasons - {None}) == 5
    assert len(SEED_PROSPECTS) == 6
