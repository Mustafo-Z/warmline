"""Extracting the structured outcome from a transcript.

Keyword-based and deliberately simple. This is *not* policy: nothing here gates
a call or raises a violation, so it lives in code rather than in a config file
a compliance reviewer would have to read. It answers "what happened on this
call" well enough to fill a row in a table, and it is labelled
`extraction_method = "deterministic"` so nobody mistakes it for comprehension.

The first live conversation showed how thin that is: an agreed meeting and a
company going public were both missed. The two fixes below came from that
transcript, which is now a regression test. An LLM extractor would do this
properly and is listed in the README as the obvious next step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from warmline.postcall.checks import CheckResult
from warmline.postcall.text import segment_sentences
from warmline.postcall.transcript import Transcript

NEWS_KEYWORDS = (
    "funding",
    "round",
    "series a",
    "series b",
    "raise",
    "launch",
    "launching",
    "hire",
    "hired",
    "hiring",
    "results",
    "report",
    "acquisition",
    "acquired",
    "partnership",
    "merger",
    "award",
    "expansion",
    "product",
    # Added after the first live call, where "going public in the next two
    # weeks" matched none of the words above.
    "going public",
    "ipo",
    "listing",
    "flotation",
)
NO_NEWS = (
    "nothing at the moment",
    "nothing right now",
    "no news",
    "nothing to share",
    "nothing coming up",
    "heads down",
    "nothing planned",
)
ASSENT_PHRASES = (
    "that would be useful",
    "sounds good",
    "go on then",
    "send something",
    "send me something",
    "please do",
)
# Single words count as assent only in a sentence with no negation in it, so
# "sure" agrees and "I'm not sure" does not.
_ASSENT_WORD = re.compile(r"\b(yes|yeah|yep|sure|fine|ok|okay|absolutely)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(not|no|don'?t|never|won'?t)\b", re.IGNORECASE)
CALLBACK = ("call me back", "try me later", "later in the year", "after the summer", "next quarter")

_MEETING_PREFERENCE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next week)\b"
    r"(\s+(morning|afternoon|evening))?",
    re.IGNORECASE,
)

MEETING_OFFER_CLAIM = "WHAT_HAPPENS_NEXT"

# An offer is not always the permitted claim word for word. In the first live
# call the agent asked "Would you be open to a short follow-up call?", which the
# claim checker rightly classifies as a question, so looking only for the
# WHAT_HAPPENS_NEXT claim missed an offer the prospect then accepted.
_MEETING_OFFER = re.compile(
    r"\b(follow[- ]up call"
    r"|call with (one of )?our consultants?"
    r"|(book|set up|arrange|schedule)\b[^.?!]{0,40}\b(call|meeting|chat))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Outcome:
    has_news: bool | None
    news_summary: str | None
    interest: str
    meeting_requested: bool
    meeting_preferences: str | None
    opt_out_requested: bool
    extraction_method: str = "deterministic"


def _contains(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def _assents(reply: str) -> bool:
    if _contains(reply, ASSENT_PHRASES):
        return True
    return any(
        _ASSENT_WORD.search(sentence) and not _NEGATION.search(sentence)
        for sentence in segment_sentences(reply)
    )


def extract_outcome(transcript: Transcript, checks: CheckResult) -> Outcome:
    prospect_turns = [turn for turn in transcript.turns if turn.role == "prospect"]
    prospect_text = " ".join(turn.text for turn in prospect_turns)

    offer_turns = [
        classification.turn_index
        for classification in checks.classifications
        if classification.rule_id == MEETING_OFFER_CLAIM
    ] + [
        turn.index
        for turn in transcript.turns
        if turn.role == "agent" and _MEETING_OFFER.search(turn.text)
    ]
    first_offer = min(offer_turns) if offer_turns else None
    replies_after_offer = (
        [turn.text for turn in prospect_turns if turn.index > first_offer]
        if first_offer is not None
        else []
    )
    meeting_requested = any(_assents(reply) for reply in replies_after_offer)

    said_no_news = _contains(prospect_text, NO_NEWS)
    news_sentence = next(
        (
            sentence
            for turn in prospect_turns
            for sentence in segment_sentences(turn.text)
            if _contains(sentence, NEWS_KEYWORDS)
        ),
        None,
    )
    if said_no_news:
        has_news: bool | None = False
    elif news_sentence is not None:
        has_news = True
    else:
        has_news = None

    if checks.opt_out_requested:
        interest = "not_interested"
    elif meeting_requested:
        interest = "interested"
    elif said_no_news:
        interest = "not_interested"
    elif _contains(prospect_text, CALLBACK):
        interest = "callback_later"
    else:
        interest = "unclear"

    preference = None
    if meeting_requested:
        match = _MEETING_PREFERENCE.search(" ".join(replies_after_offer))
        preference = match.group(0) if match else None

    return Outcome(
        has_news=None if checks.opt_out_requested and news_sentence is None else has_news,
        news_summary=news_sentence if has_news else None,
        interest=interest,
        meeting_requested=meeting_requested,
        meeting_preferences=preference,
        opt_out_requested=checks.opt_out_requested,
    )
