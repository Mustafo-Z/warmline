"""The agent's configuration is policy, so it is tested like policy.

SPEC 4.4, 5.1, 9.1. The prompt, the pinned opening and the claim allowlist live
in version-controlled files; these tests assert they are well formed, that they
agree with each other, and that the line the agent actually says survives its
own rules.

The full Tier 1 claim check on the opening line arrives with the post-call
checker in step 5. What can be asserted without it — the disclosure patterns and
the prohibited-pattern scan — is asserted here.
"""

from __future__ import annotations

import re
import shutil

import pytest

from warmline.agent import load_agent_config, load_first_turn, load_system_prompt
from warmline.config import (
    POLICY_FILES,
    load_claims_config,
    load_disclosure_config,
    load_policy_config,
)


def prompt_text() -> str:
    """The prompt with whitespace collapsed, so assertions are about content.

    The prompt is hard-wrapped for reading in a diff; a sentence that spans two
    lines is still the same sentence.
    """
    return re.sub(r"\s+", " ", load_system_prompt()).lower()


@pytest.fixture(scope="module")
def claims():
    return load_claims_config()


@pytest.fixture(scope="module")
def disclosure():
    return load_disclosure_config()


@pytest.fixture(scope="module")
def agent():
    return load_agent_config()


# --- the files are well formed ---------------------------------------------


def test_every_pattern_compiles(claims, disclosure):
    patterns = (
        *claims.prohibited_patterns,
        *claims.non_claim_patterns,
        *disclosure.accepted_patterns,
    )

    assert patterns
    assert all(isinstance(rule.pattern, re.Pattern) for rule in patterns)


def test_claim_ids_are_unique_and_named(claims):
    ids = [claim.id for claim in claims.permitted_claims]

    assert len(ids) == len(set(ids))
    assert all(claim.canonical.strip() for claim in claims.permitted_claims)


def test_every_prohibited_pattern_carries_a_reason(claims):
    """The reason is what a reviewer reads when a violation fires."""
    assert all(rule.reason for rule in claims.prohibited_patterns)


def test_the_policy_files_all_exist_and_are_in_the_digest():
    assert len(POLICY_FILES) == 4
    assert load_policy_config().config_digest.startswith("sha256:")


def test_the_digest_changes_when_the_allowlist_changes(tmp_path):
    """Editing what the agent may say is a policy change, and is recorded as one."""
    directory = tmp_path / "policy"
    shutil.copytree("policy", directory)
    before = load_policy_config(directory).config_digest

    target = directory / "permitted_claims.yaml"
    target.write_text(target.read_text().replace("under a minute", "under two minutes"))

    assert load_policy_config(directory).config_digest != before


# --- the three sources agree on who is calling -----------------------------


def test_the_principal_is_the_same_everywhere(claims, disclosure, agent):
    assert claims.principal == disclosure.principal == agent.principal == "Meridian Communications"


def test_every_canonical_claim_naming_a_principal_names_the_right_one(claims):
    for claim in claims.permitted_claims:
        if "communications" in claim.canonical.lower():
            assert claims.principal in claim.canonical


# --- the opening line survives its own rules -------------------------------


def test_the_pinned_first_turn_discloses_the_ai(disclosure):
    first_turn = load_first_turn()

    assert any(rule.pattern.search(first_turn) for rule in disclosure.accepted_patterns)


def test_the_disclosure_is_in_the_first_sentence_not_merely_the_first_turn(disclosure):
    """Stricter than the spec requires, and free."""
    first_sentence = load_first_turn().split(".")[0]

    assert any(rule.pattern.search(first_sentence) for rule in disclosure.accepted_patterns)


def test_the_pinned_first_turn_names_the_principal(disclosure):
    assert disclosure.must_also_mention_principal
    assert disclosure.principal in load_first_turn()


def test_the_pinned_first_turn_is_three_sentences(claims):
    """SPEC 4.4: the commitment is its own sentence so the checker sees it.

    Counted crudely here. The real segmenter arrives with the post-call checker
    in step 5, and asserts this properly against the same text.
    """
    first_turn = load_first_turn()

    assert first_turn.count(".") + first_turn.count("?") == 3
    assert "I'll keep this under a minute." in first_turn


def test_no_prohibited_pattern_matches_the_opening_line(claims):
    """Tier 1a, run against the agent's own script."""
    first_turn = load_first_turn()

    fired = [rule.id for rule in claims.prohibited_patterns if rule.pattern.search(first_turn)]

    assert fired == []


def test_no_permitted_claim_matches_a_prohibited_pattern(claims):
    """A claim we allow must not be a thing we forbid. Internal consistency."""
    conflicts = {
        claim.id: rule.id
        for claim in claims.permitted_claims
        for rule in claims.prohibited_patterns
        if rule.pattern.search(claim.canonical)
    }

    assert conflicts == {}


# --- the prompt says the things it has to say ------------------------------


def test_the_system_prompt_states_the_disclosure_requirement():
    prompt = prompt_text()

    assert "you are an ai" in prompt or "an ai assistant" in prompt
    assert "never claim or imply that you are a person" in prompt


def test_the_system_prompt_carries_the_voicemail_rule():
    """SPEC 4.4: say nothing to a machine. Instructed here, not verified anywhere."""
    prompt = prompt_text()

    assert "voicemail" in prompt
    assert "never leave a message" in prompt


def test_the_system_prompt_forbids_what_the_allowlist_forbids(claims):
    """The prompt and the checker should be describing the same limits."""
    prompt = prompt_text()

    for phrase in ("price", "guarantee", "timeline", "publication", "competitor"):
        assert phrase in prompt


def test_the_system_prompt_tells_the_agent_to_admit_a_limit_rather_than_invent():
    prompt = prompt_text()

    assert "inventing a plausible answer is worse than admitting the limit" in prompt


# --- the provider is not wired ---------------------------------------------


def test_the_agent_config_declares_the_provider_unwired(agent):
    """SPEC 2.1: nothing dials. If this ever flips, it should flip deliberately."""
    assert agent.provider_wired is False
    assert agent.end_call_on_voicemail is True
