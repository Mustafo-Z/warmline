"""The shipped policy config is part of the contract, so it is asserted too.

SPEC 3 and SPEC 4.2 state these values. If someone widens a window or raises a
limit, that is a policy change and it should require editing a test that says
so out loud.
"""

from __future__ import annotations

from datetime import time

from warmline.config import config_digest, load_policy_config


def test_default_profile_is_ae(config):
    assert config.default_profile == "AE"


def test_the_three_profiles_match_the_spec(config):
    assert set(config.profiles) == {"AE", "UK", "US"}

    ae = config.profiles["AE"]
    assert ae.days == ("sun", "mon", "tue", "wed", "thu")
    assert (ae.window_start, ae.window_end) == (time(9, 0), time(18, 0))

    uk = config.profiles["UK"]
    assert uk.days == ("mon", "tue", "wed", "thu", "fri")
    assert (uk.window_start, uk.window_end) == (time(9, 0), time(18, 0))

    us = config.profiles["US"]
    assert us.days == ("mon", "tue", "wed", "thu", "fri")
    assert (us.window_start, us.window_end) == (time(9, 0), time(20, 0))


def test_attempt_limits_match_the_spec(config):
    assert config.attempt_limits.max_per_24h == 1
    assert config.attempt_limits.max_per_rolling_7d == 3


def test_timezone_mismatch_blocks_by_default(config):
    assert config.timezone_mismatch_action == "block"


def test_every_verified_number_is_stored_normalised(config):
    for key, entry in config.verified_numbers.items():
        assert key == entry.phone_e164
        assert key.startswith("+")


def test_config_digest_changes_when_a_policy_file_changes(tmp_path):
    """A stored decision must be re-checkable against the config that made it."""
    first = tmp_path / "a.yaml"
    first.write_text("window: 09:00\n")
    before = config_digest([first])

    first.write_text("window: 08:00\n")

    assert config_digest([first]) != before


def test_config_digest_is_stable_across_loads():
    assert load_policy_config().config_digest == load_policy_config().config_digest
