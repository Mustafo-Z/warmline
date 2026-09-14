"""Real conversations with the live agent. SPEC 6.5, SPEC 9.

Each file in evals/live/ is a transcript fetched from the running deployment
after a real browser session, committed as ElevenLabs stored it. They go through
the same checks as the scripted scenarios, and the result is pinned here.

The first live conversation is the reason two things in the extractor changed:
it is the regression test for both.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from warmline.agent import load_first_turn
from warmline.config import load_claims_config, load_disclosure_config
from warmline.postcall.checks import run_checks
from warmline.postcall.outcome import extract_outcome
from warmline.postcall.transcript import normalise_transcript

LIVE = Path(__file__).resolve().parents[1] / "evals" / "live"
GOLDEN = Path(__file__).parent / "golden" / "live_unclassified.json"

FIRST_CALL = "conv_3001m2f91xb1e2y9adt7ykxrh0sj"
CUT_OFF_CALL = "conv_4901m2f955the5s953s6146aazzc"


def fixtures() -> dict[str, dict]:
    return {
        raw["conversation_id"]: raw
        for raw in (json.loads(path.read_text()) for path in sorted(LIVE.glob("*.json")))
    }


@pytest.fixture(scope="module")
def configs():
    return load_claims_config(), load_disclosure_config()


def check(conversation_id: str, configs):
    raw = fixtures()[conversation_id]
    transcript = normalise_transcript(raw, source="live", conversation_id=conversation_id)
    return transcript, run_checks(transcript, *configs, pinned_opening=load_first_turn())


def test_every_live_fixture_is_labelled_live_and_names_its_agent():
    loaded = fixtures()

    assert loaded, "no live transcripts committed"
    for raw in loaded.values():
        assert raw["source"] == "live"
        assert raw["agent_id"].startswith("agent_")
        assert raw["note"].strip()


def test_the_first_live_call_disclosed_in_its_opening_turn(configs):
    _transcript, result = check(FIRST_CALL, configs)

    assert result.disclosure_ok is True


def test_the_first_live_call_encouraged_coverage_of_an_imminent_listing(configs):
    """The call that produced the sensitive-news rule.

    The prospect said the company was going public in two weeks. The agent
    called it worth pitching and offered to discuss how to approach the
    coverage. No claim or commitment rule fired; this is the only thing wrong.
    """
    _transcript, result = check(FIRST_CALL, configs)

    assert [(v.code, v.quote) for v in result.violations] == [
        ("SENSITIVE_NEWS", "Going public is definitely something that could be worth pitching."),
        (
            "SENSITIVE_NEWS",
            "Would you be open to a short follow-up call with them "
            "to discuss how to approach the coverage?",
        ),
    ]


def test_unclassified_live_sentences_match_the_golden_file(configs):
    """The blind spot, on real speech.

    The first live call left most of the agent's sentences unclassified — far
    more than any scenario. None broke a rule, but none was verified either,
    and the page now says so instead of showing a clean pass.
    """
    actual = {cid: list(check(cid, configs)[1].unclassified) for cid in fixtures()}

    assert actual == json.loads(GOLDEN.read_text())


def test_the_meeting_offered_as_a_question_is_extracted(configs):
    """Regression: the agent asked "Would you be open to a short follow-up call?"

    The claim checker classifies that, correctly, as a question rather than the
    permitted booking claim, and the extractor only looked for the claim, so an
    agreed meeting was recorded as meeting_requested = false.
    """
    transcript, result = check(FIRST_CALL, configs)

    outcome = extract_outcome(transcript, result)

    assert outcome.meeting_requested is True
    assert outcome.interest == "interested"


def test_going_public_is_recognised_as_news(configs):
    """Regression: "going public in the next two weeks" matched no news keyword."""
    transcript, result = check(FIRST_CALL, configs)

    outcome = extract_outcome(transcript, result)

    assert outcome.has_news is True
    assert "going public" in outcome.news_summary


def test_the_accidental_call_is_recorded_as_ended_during_the_opening(configs):
    """It ended at "Hi,..." before anyone replied: stored, not scored."""
    _transcript, result = check(CUT_OFF_CALL, configs)

    assert result.ended_during_opening is True
    assert result.violations == ()
