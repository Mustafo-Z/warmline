"""Post-call checks. SPEC 4.5, 5.2.

Pure: given a transcript and the policy config, produce violations and a
classification for every agent sentence. Nothing here reads a file or a
database, so the same function runs in a test, in the API and in the eval.

Every violation carries the quoted sentence, the turn index and the rule id
that fired, so a reviewer can check the checker without re-reading the call.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from warmline.policy.models import ClaimsConfig, DisclosureConfig
from warmline.postcall.text import (
    coverage,
    has_numeric_token,
    proper_nouns,
    segment_sentences,
    superlatives,
    tokens,
)
from warmline.postcall.transcript import Transcript

DISCLOSURE_MISSING = "DISCLOSURE_MISSING"
DISCLOSURE_NOT_IN_FIRST_TURN = "DISCLOSURE_NOT_IN_FIRST_TURN"
UNPERMITTED_CLAIM = "UNPERMITTED_CLAIM"
OUT_OF_SCOPE_COMMITMENT = "OUT_OF_SCOPE_COMMITMENT"
OPT_OUT_NOT_HONOURED = "OPT_OUT_NOT_HONOURED"
SENSITIVE_NEWS = "SENSITIVE_NEWS"

#: Claims that are still fine to make after a prospect has asked to be left
#: alone. Anything else is continuing to pitch.
CLAIMS_ALLOWED_AFTER_OPT_OUT = frozenset({"OPT_OUT"})


@dataclass(frozen=True)
class Violation:
    code: str
    rule_id: str | None
    turn_index: int
    quote: str
    tier: str = "1"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Classification:
    turn_index: int
    sentence: str
    verdict: str  # prohibited | non_claim | permitted | commitment | unclassified
    rule_id: str | None = None


@dataclass(frozen=True)
class CheckResult:
    disclosure_ok: bool
    violations: tuple[Violation, ...] = ()
    classifications: tuple[Classification, ...] = ()
    opt_out_requested: bool = False
    opt_out_turn_index: int | None = None
    ended_during_opening: bool = False

    @property
    def codes(self) -> set[str]:
        return {violation.code for violation in self.violations}

    @property
    def unclassified(self) -> tuple[str, ...]:
        return tuple(c.sentence for c in self.classifications if c.verdict == "unclassified")


# --- disclosure ------------------------------------------------------------


def check_disclosure(
    transcript: Transcript, config: DisclosureConfig
) -> tuple[bool, list[Violation]]:
    """Did the agent say it was an AI, and did it say so in its first turn?"""
    agent_turns = transcript.agent_turns
    if not agent_turns:
        return False, [
            Violation(DISCLOSURE_MISSING, None, 0, "", tier="1"),
        ]

    for position, turn in enumerate(agent_turns, start=1):
        matched = any(rule.pattern.search(turn.text) for rule in config.accepted_patterns)
        if not matched:
            continue
        if config.must_also_mention_principal and config.principal.lower() not in turn.text.lower():
            continue

        if position == config.required_in_agent_turn:
            return True, []
        return False, [
            Violation(DISCLOSURE_NOT_IN_FIRST_TURN, None, turn.index, turn.text, tier="1")
        ]

    return False, [Violation(DISCLOSURE_MISSING, None, agent_turns[0].index, agent_turns[0].text)]


# --- claims ----------------------------------------------------------------


def _matches_permitted(sentence: str, config: ClaimsConfig) -> str | None:
    """The claim this sentence is a paraphrase of, if any. SPEC 5.2 Tier 1b.

    Checked against the canonical and every accepted form of each claim.
    """
    sentence_tokens = set(tokens(sentence))

    for claim in config.permitted_claims:
        for form in (claim.canonical, *claim.also_accepted):
            if coverage(sentence, form) < config.paraphrase_threshold:
                continue

            form_tokens = set(tokens(form))
            # A paraphrase may drop words. It may not introduce a number, a name
            # or a superlative: those are what an invented claim is made of.
            introduced = sentence_tokens - form_tokens
            if any(any(ch.isdigit() for ch in token) for token in introduced):
                continue
            if superlatives(sentence) and not superlatives(form):
                continue
            # Absent from the accepted form, not absent altogether: WHO_WE_ARE
            # contains "AI", so a sentence containing "AI" introduces nothing.
            introduced_names = {
                name.lower() for name in proper_nouns(sentence, principal=config.principal)
            } - {name.lower() for name in proper_nouns(form, principal=config.principal)}
            if introduced_names:
                continue
            if not claim.may_paraphrase and sentence.strip().rstrip(".") != form.rstrip("."):
                continue
            return claim.id

    return None


def _is_non_claim(sentence: str, config: ClaimsConfig) -> str | None:
    """Greetings, acknowledgements, questions and scheduling logistics.

    Eligibility first: a sentence carrying a number or a name is never waved
    through, however it is punctuated. Without that guard, "We work with 400
    companies, do you have news?" reads as a harmless question and the invented
    figure is never checked.
    """
    eligibility = config.non_claim_eligibility
    if eligibility.no_numeric_tokens and has_numeric_token(sentence):
        return None
    if eligibility.no_proper_nouns_except_principal and proper_nouns(
        sentence, principal=config.principal
    ):
        return None

    for rule in config.non_claim_patterns:
        if rule.pattern.fullmatch(sentence.strip()):
            return rule.id
    return None


def check_claims(
    transcript: Transcript, config: ClaimsConfig
) -> tuple[list[Violation], list[Classification]]:
    violations: list[Violation] = []
    classifications: list[Classification] = []

    for turn in transcript.agent_turns:
        for sentence in segment_sentences(turn.text):
            # Tier 1a. Blunt, first, and final for this sentence.
            prohibited = next(
                (rule for rule in config.prohibited_patterns if rule.pattern.search(sentence)), None
            )
            if prohibited is not None:
                violations.append(
                    Violation(UNPERMITTED_CLAIM, prohibited.id, turn.index, sentence, tier="1a")
                )
                classifications.append(
                    Classification(turn.index, sentence, "prohibited", prohibited.id)
                )
                continue

            # Tier 1b.
            non_claim = _is_non_claim(sentence, config)
            if non_claim is not None:
                classifications.append(Classification(turn.index, sentence, "non_claim", non_claim))
                continue

            claim_id = _matches_permitted(sentence, config)
            if claim_id is not None:
                classifications.append(Classification(turn.index, sentence, "permitted", claim_id))
                continue

            # Commitments are looked for in the residue. A sentence the
            # allowlist already accounts for is not an out-of-scope commitment:
            # "I'll send a calendar invite" is permitted scheduling, and
            # checking it earlier would report it as agreeing to send a
            # document.
            commitment = next(
                (rule for rule in config.commitment_patterns if rule.pattern.search(sentence)), None
            )
            if commitment is not None:
                violations.append(
                    Violation(
                        OUT_OF_SCOPE_COMMITMENT, commitment.id, turn.index, sentence, tier="1"
                    )
                )
                classifications.append(
                    Classification(turn.index, sentence, "commitment", commitment.id)
                )
                continue

            classifications.append(Classification(turn.index, sentence, "unclassified", None))

    return violations, classifications


# --- opt-out ---------------------------------------------------------------


def find_opt_out(
    transcript: Transcript, config: ClaimsConfig
) -> tuple[bool, int | None, str | None]:
    for turn in transcript.turns:
        if turn.role != "prospect":
            continue
        for rule in config.opt_out_patterns:
            if rule.pattern.search(turn.text):
                return True, turn.index, rule.id
    return False, None, None


def check_opt_out_honoured(
    transcript: Transcript, classifications: list[Classification], opt_out_turn: int
) -> list[Violation]:
    """Did the agent stop, or did it keep pitching?"""
    for classification in classifications:
        if classification.turn_index <= opt_out_turn:
            continue
        if classification.verdict == "permitted" and (
            classification.rule_id in CLAIMS_ALLOWED_AFTER_OPT_OUT
        ):
            continue
        if classification.verdict in {"non_claim"}:
            continue
        return [
            Violation(
                OPT_OUT_NOT_HONOURED,
                classification.rule_id,
                classification.turn_index,
                classification.sentence,
            )
        ]
    return []


# --- the whole check -------------------------------------------------------


# --- market-sensitive news -------------------------------------------------


def find_sensitive_news(transcript: Transcript, config: ClaimsConfig) -> tuple[int, str] | None:
    """The first prospect turn that raises market-sensitive news, and what kind."""
    for turn in transcript.turns:
        if turn.role != "prospect":
            continue
        for rule in config.sensitive_news_patterns:
            if rule.pattern.search(turn.text):
                return turn.index, rule.id
    return None


def check_sensitive_news(transcript: Transcript, config: ClaimsConfig) -> list[Violation]:
    """Did the agent encourage publicity for market-sensitive news the prospect raised?

    Only sentences after the prospect raised it count. The agent asking about
    news in general, or offering a consultant, is not a violation; calling an
    imminent listing "worth pitching" is.
    """
    raised = find_sensitive_news(transcript, config)
    if raised is None:
        return []
    raised_at, _kind = raised

    violations: list[Violation] = []
    for turn in transcript.agent_turns:
        if turn.index <= raised_at:
            continue
        for sentence in segment_sentences(turn.text):
            rule = next(
                (r for r in config.sensitive_engagement_patterns if r.pattern.search(sentence)),
                None,
            )
            if rule is not None:
                violations.append(Violation(SENSITIVE_NEWS, rule.id, turn.index, sentence))
    return violations


# --- calls that never got going ---------------------------------------------


def ended_during_opening(transcript: Transcript, pinned_opening: str | None) -> bool:
    """The call ended while the pinned opening was still being spoken.

    True only when nobody else said anything and the agent's one turn is a
    strict prefix of the pinned opening — "Hi,..." when the opening begins
    "Hi, I'm an AI assistant". Such a call is recorded but not scored as a
    missing disclosure: the line that makes the disclosure was cut off before
    anyone could hear it, and nothing else was said. An agent that speaks
    without disclosing, even with no reply, is still a violation.
    """
    if not pinned_opening:
        return False
    if any(turn.role == "prospect" for turn in transcript.turns):
        return False
    agent_turns = transcript.agent_turns
    if len(agent_turns) != 1:
        return False
    spoken = re.sub(r"[.…\s]+$", "", agent_turns[0].text.strip())
    opening = pinned_opening.strip()
    return bool(spoken) and len(spoken) < len(opening) and opening.startswith(spoken)


# --- the whole check -------------------------------------------------------


def run_checks(
    transcript: Transcript,
    claims: ClaimsConfig,
    disclosure: DisclosureConfig,
    *,
    pinned_opening: str | None = None,
) -> CheckResult:
    abandoned = ended_during_opening(transcript, pinned_opening)
    disclosure_ok, violations = check_disclosure(transcript, disclosure)
    if abandoned:
        violations = []

    claim_violations, classifications = check_claims(transcript, claims)
    violations = [*violations, *claim_violations]

    opted_out, opt_out_turn, _rule = find_opt_out(transcript, claims)
    if opted_out and opt_out_turn is not None:
        violations += check_opt_out_honoured(transcript, classifications, opt_out_turn)

    violations += check_sensitive_news(transcript, claims)

    return CheckResult(
        disclosure_ok=disclosure_ok,
        violations=tuple(violations),
        classifications=tuple(classifications),
        opt_out_requested=opted_out,
        opt_out_turn_index=opt_out_turn,
        ended_during_opening=abandoned,
    )
