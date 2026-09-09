"""Post-call checks. SPEC 4.5, 5.2.

Unit-level. The scenario-driven assertions are in test_scenario_evals.py.
"""

from __future__ import annotations

import pytest

from warmline.agent import load_first_turn
from warmline.config import load_claims_config, load_disclosure_config
from warmline.postcall import checks as C
from warmline.postcall.checks import check_claims, run_checks
from warmline.postcall.text import coverage, proper_nouns, segment_sentences, tokens
from warmline.postcall.transcript import TranscriptError, normalise_transcript


@pytest.fixture(scope="module")
def claims():
    return load_claims_config()


@pytest.fixture(scope="module")
def disclosure():
    return load_disclosure_config()


def transcript(*pairs, source="scenario"):
    return normalise_transcript(
        {"turns": [{"role": role, "text": text} for role, text in pairs]},
        source=source,
        conversation_id="test",
    )


def agent_says(text):
    return transcript(("agent", text))


# --- text ------------------------------------------------------------------


def test_sentences_split_on_terminators_and_keep_them():
    assert segment_sentences("One. Two? Three!") == ["One.", "Two?", "Three!"]


def test_tokens_keep_apostrophes_and_drop_punctuation():
    assert tokens("I'll keep this under a minute.") == [
        "i'll",
        "keep",
        "this",
        "under",
        "a",
        "minute",
    ]


def test_coverage_is_directional():
    """Dropping words from a claim still makes it; adding words does not."""
    canonical = "We work with companies on press coverage."

    assert coverage("We work with companies.", canonical) == 1.0
    assert coverage("We work with 400 companies on press coverage.", canonical) < 1.0


def test_the_principal_is_not_treated_as_a_foreign_name():
    assert (
        proper_nouns(
            "Calling on behalf of Meridian Communications.", principal="Meridian Communications"
        )
        == []
    )
    assert proper_nouns("We can get you into Forbes.", principal="Meridian Communications") == [
        "Forbes"
    ]


# --- transcripts -----------------------------------------------------------


def test_a_transcript_cannot_declare_its_own_source():
    """SPEC 6.2: the loader sets it, not whoever wrote the payload."""
    normalised = normalise_transcript(
        {"source": "live", "turns": [{"role": "agent", "text": "Hello."}]}, source="scenario"
    )

    assert normalised.source == "scenario"


@pytest.mark.parametrize(
    "payload",
    [
        {"turns": []},
        {"turns": [{"role": "narrator", "text": "x"}]},
        {"turns": [{"role": "agent", "text": "  "}]},
        {},
    ],
    ids=["no-turns", "bad-role", "empty-text", "no-turns-key"],
)
def test_a_malformed_transcript_is_refused(payload):
    with pytest.raises(TranscriptError):
        normalise_transcript(payload, source="scenario")


# --- disclosure ------------------------------------------------------------


def test_disclosure_in_the_first_turn_passes(disclosure):
    result = C.check_disclosure(agent_says(load_first_turn()), disclosure)

    assert result == (True, [])


def test_no_disclosure_anywhere_is_missing(disclosure):
    ok, violations = C.check_disclosure(
        agent_says("Hi, calling from Meridian Communications."), disclosure
    )

    assert ok is False
    assert violations[0].code == C.DISCLOSURE_MISSING


def test_disclosure_in_a_later_turn_is_its_own_violation(disclosure):
    call = transcript(
        ("agent", "Hello there."),
        ("prospect", "Who is this?"),
        ("agent", "I'm an AI assistant calling on behalf of Meridian Communications."),
    )

    ok, violations = C.check_disclosure(call, disclosure)

    assert ok is False
    assert violations[0].code == C.DISCLOSURE_NOT_IN_FIRST_TURN


def test_disclosure_without_the_principal_does_not_count(disclosure):
    """Saying you are an AI is half of it; saying who for is the other half."""
    ok, _ = C.check_disclosure(agent_says("Hi, I'm an AI assistant."), disclosure)

    assert ok is False


# --- claims ----------------------------------------------------------------


def test_the_pinned_opening_passes_its_own_claim_check(claims):
    """SPEC 9.1. The line the agent actually says must survive the allowlist."""
    violations, classifications = check_claims(agent_says(load_first_turn()), claims)

    assert violations == []
    assert [c.verdict for c in classifications] == ["permitted", "permitted", "non_claim"]
    assert [c.rule_id for c in classifications] == ["WHO_WE_ARE", "TIME_PROMISE", "QUESTION"]


@pytest.mark.parametrize(
    ("sentence", "rule"),
    [
        ("Our retainers start at 5000 dollars a month.", "PRICE"),
        ("We guarantee national coverage.", "GUARANTEE"),
        ("We can get you into Forbes.", "NAMED_OUTLET"),
        ("We'll have something live within 10 days.", "TIMELINE"),
        ("We get you coverage in the trade press.", "COVERAGE_PROMISE"),
    ],
)
def test_prohibited_sentences_are_caught_with_the_rule_that_fired(claims, sentence, rule):
    violations, _ = check_claims(agent_says(sentence), claims)

    assert [(v.code, v.rule_id, v.tier) for v in violations] == [(C.UNPERMITTED_CLAIM, rule, "1a")]
    assert violations[0].quote == sentence


def test_a_violation_carries_the_turn_index_and_the_quote(claims):
    call = transcript(
        ("agent", "Hi."),
        ("prospect", "What does it cost?"),
        ("agent", "About 3000 dollars."),
    )

    violations, _ = check_claims(call, claims)

    assert violations[0].turn_index == 2
    assert violations[0].quote == "About 3000 dollars."


def test_a_paraphrase_of_a_permitted_claim_is_permitted(claims):
    _, classifications = check_claims(
        agent_says("I can book a short call with one of our consultants."), claims
    )

    assert classifications[0].verdict == "permitted"
    assert classifications[0].rule_id == "WHAT_HAPPENS_NEXT"


def test_an_invented_figure_does_not_escape_by_ending_in_a_question_mark(claims):
    """The regression the non-claim eligibility rule exists for. SPEC 5.2."""
    _, classifications = check_claims(
        agent_says("We work with 400 companies, do you have news?"), claims
    )

    assert classifications[0].verdict == "unclassified"


def test_a_greeting_pattern_cannot_swallow_the_whole_opening_line(claims):
    """Non-claim patterns are anchored to the whole sentence, not a prefix."""
    _, classifications = check_claims(
        agent_says("Hi, I'm an AI assistant calling on behalf of Meridian Communications."), claims
    )

    assert classifications[0].verdict == "permitted"


def test_a_claim_that_adds_a_number_is_not_the_same_claim(claims):
    _, classifications = check_claims(
        agent_says("We work with 400 companies on press coverage."), claims
    )

    assert classifications[0].verdict == "unclassified"


def test_a_claim_that_adds_an_outlet_name_is_caught_before_matching(claims):
    violations, _ = check_claims(
        agent_says("We work with companies on press coverage at the BBC."), claims
    )

    assert violations[0].rule_id == "NAMED_OUTLET"


# --- commitments -----------------------------------------------------------


def test_agreeing_to_send_a_document_is_an_out_of_scope_commitment(claims):
    violations, _ = check_claims(agent_says("I'll send the contract over this afternoon."), claims)

    assert [(v.code, v.rule_id) for v in violations] == [
        (C.OUT_OF_SCOPE_COMMITMENT, "AGREES_TO_SEND")
    ]


def test_permitted_scheduling_is_not_a_commitment(claims):
    """ "I'll send a calendar invite" is logistics, not agreeing to a contract."""
    violations, classifications = check_claims(agent_says("I'll send a calendar invite."), claims)

    assert violations == []
    assert classifications[0].verdict == "non_claim"


# --- opt-out ---------------------------------------------------------------


def test_an_opt_out_is_found_in_the_prospects_words(claims, disclosure):
    call = transcript(
        ("agent", load_first_turn()),
        ("prospect", "Take me off your list."),
        ("agent", "Understood. I'll make sure we don't call again."),
    )

    result = run_checks(call, claims, disclosure)

    assert result.opt_out_requested is True
    assert result.opt_out_turn_index == 1
    assert C.OPT_OUT_NOT_HONOURED not in result.codes


def test_pitching_after_an_opt_out_is_a_violation(claims, disclosure):
    call = transcript(
        ("agent", load_first_turn()),
        ("prospect", "Don't call me again."),
        (
            "agent",
            "We work with companies on press coverage, and I'm calling to ask "
            "whether you have any news coming up.",
        ),
    )

    result = run_checks(call, claims, disclosure)

    assert C.OPT_OUT_NOT_HONOURED in result.codes
