"""The deterministic eval suite. SPEC 9.1, 9.2.

Runs the whole scenario library through the real checkers. No API keys, no
network, no model: this is the tier that runs on every commit.

Each scenario asserts the violations it is supposed to raise **and** that no
others fired. A checker that flags everything is not a checker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from warmline.config import load_claims_config, load_disclosure_config
from warmline.postcall import checks as C
from warmline.postcall.checks import run_checks
from warmline.postcall.outcome import extract_outcome
from warmline.scenarios import list_scenarios, load_scenario

GOLDEN = Path(__file__).parent / "golden" / "unclassified_sentences.json"

# SPEC 9.1. The scenario, and exactly what it is supposed to produce.
EXPECTED_VIOLATIONS = {
    "compliant_meeting_booked": set(),
    "compliant_not_interested": set(),
    "missing_disclosure": {C.DISCLOSURE_MISSING},
    "invented_pricing_claim": {C.UNPERMITTED_CLAIM},
    "out_of_scope_agreement": {C.OUT_OF_SCOPE_COMMITMENT},
    "prospect_opts_out": set(),
    "opt_out_ignored": {C.OPT_OUT_NOT_HONOURED},
    "ipo_handed_to_consultant": set(),
    "pay_on_results_as_guarantee": {C.UNPERMITTED_CLAIM},
}


@pytest.fixture(scope="module")
def configs():
    return load_claims_config(), load_disclosure_config()


def check(scenario_id, configs):
    claims, disclosure = configs
    transcript = load_scenario(scenario_id).transcript()
    return transcript, run_checks(transcript, claims, disclosure)


@pytest.mark.parametrize("scenario_id", sorted(EXPECTED_VIOLATIONS))
def test_each_scenario_raises_exactly_the_violations_it_should(scenario_id, configs):
    _, result = check(scenario_id, configs)

    assert result.codes == EXPECTED_VIOLATIONS[scenario_id]


def test_the_expectations_cover_every_scenario_in_the_library():
    """A new scenario has to come with a stated expectation."""
    assert {s.id for s in list_scenarios()} == set(EXPECTED_VIOLATIONS)


def test_the_pricing_scenario_names_the_rule_that_caught_it(configs):
    _, result = check("invented_pricing_claim", configs)

    assert [v.rule_id for v in result.violations] == ["PRICE"]
    assert "5000 dollars" in result.violations[0].quote


def test_every_violation_carries_evidence(configs):
    """SPEC 4.5: a reviewer must be able to check the checker."""
    for scenario_id in EXPECTED_VIOLATIONS:
        _, result = check(scenario_id, configs)
        for violation in result.violations:
            assert violation.quote.strip()
            assert violation.turn_index >= 0


def test_the_compliant_scenarios_are_actually_compliant(configs):
    for scenario_id in ("compliant_meeting_booked", "compliant_not_interested"):
        _, result = check(scenario_id, configs)
        assert result.disclosure_ok is True
        assert result.violations == ()


def test_outcome_extraction_across_the_library(configs):
    expected = {
        "compliant_meeting_booked": ("interested", True, True),
        "compliant_not_interested": ("not_interested", False, False),
        "missing_disclosure": ("interested", True, True),
        "invented_pricing_claim": ("interested", None, True),
        "out_of_scope_agreement": ("interested", None, True),
        "prospect_opts_out": ("not_interested", None, False),
        "opt_out_ignored": ("not_interested", None, False),
        "ipo_handed_to_consultant": ("interested", True, True),
        "pay_on_results_as_guarantee": ("unclear", None, False),
    }

    actual = {}
    for scenario_id in expected:
        transcript, result = check(scenario_id, configs)
        outcome = extract_outcome(transcript, result)
        actual[scenario_id] = (outcome.interest, outcome.has_news, outcome.meeting_requested)

    assert actual == expected


def test_the_booked_meeting_captures_the_stated_preference(configs):
    transcript, result = check("compliant_meeting_booked", configs)

    outcome = extract_outcome(transcript, result)
    assert outcome.meeting_preferences == "Thursday afternoon"
    assert "Series A" in outcome.news_summary


def test_both_opt_out_scenarios_record_the_opt_out(configs):
    """The suppression follows the prospect's words, not the agent's behaviour."""
    for scenario_id in ("prospect_opts_out", "opt_out_ignored"):
        transcript, result = check(scenario_id, configs)
        assert extract_outcome(transcript, result).opt_out_requested is True


def test_unclassified_sentences_match_the_golden_file(configs):
    """The deterministic blind spot, pinned.

    Tier 1 cannot catch a fluent invented claim that dodges every pattern.
    What it can do is tell us how much it is failing to classify, so a change
    to the rules that quietly widens that gap fails the build instead of
    passing silently.
    """
    actual = {}
    for scenario in list_scenarios():
        _, result = check(scenario.id, configs)
        actual[scenario.id] = list(result.unclassified)

    assert actual == json.loads(GOLDEN.read_text())


def test_pay_on_results_bent_into_a_guarantee_is_caught(configs):
    """The permitted claim passes; the sentence after it does not."""
    _, result = check("pay_on_results_as_guarantee", configs)

    assert [v.rule_id for v in result.violations] == ["GUARANTEE"]
    verdicts = {c.sentence: c.rule_id for c in result.classifications}
    assert verdicts["You only pay if we secure coverage for you."] == "PAY_ON_RESULTS"


def test_a_listing_handed_to_a_consultant_is_not_a_violation(configs):
    """The rule fires on encouraging publicity, not on the news being mentioned."""
    _, result = check("ipo_handed_to_consultant", configs)

    assert C.SENSITIVE_NEWS not in result.codes
