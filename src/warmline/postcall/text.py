"""Sentence segmentation and token inspection. SPEC 5.2.

Deterministic and dull on purpose: a splitter on `.`, `?` and `!`, and a
tokeniser that lowercases and strips punctuation but keeps apostrophes. No
model, no language pack, nothing that behaves differently between runs.
"""

from __future__ import annotations

import re

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[a-z0-9'’]+")
_HAS_DIGIT = re.compile(r"\d")

#: Words that make a sentence a stronger assertion than its canonical claim.
SUPERLATIVES = frozenset(
    {"best", "biggest", "fastest", "largest", "leading", "most", "top", "greatest", "premier"}
)


def segment_sentences(text: str) -> list[str]:
    """Split a turn into sentences, keeping their terminating punctuation."""
    return [part.strip() for part in _SENTENCE_BREAK.split(text.strip()) if part.strip()]


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower().replace("’", "'"))


def has_numeric_token(text: str) -> bool:
    return any(_HAS_DIGIT.search(token) for token in tokens(text))


def proper_nouns(sentence: str, *, principal: str = "") -> list[str]:
    """Capitalised words after the first, minus the principal's own words.

    A heuristic, and it is meant to be a blunt one: its job is to stop a
    sentence carrying a name from being waved through as a greeting, not to do
    named-entity recognition.
    """
    allowed = {word.lower() for word in tokens(principal)} | {"i", "i'm", "i'll", "i've"}
    words = re.findall(r"[A-Za-z'’]+", sentence)
    return [
        word
        for index, word in enumerate(words)
        if index > 0 and word[:1].isupper() and word.lower() not in allowed
    ]


def superlatives(text: str) -> list[str]:
    return [token for token in tokens(text) if token in SUPERLATIVES]


def coverage(sentence: str, canonical: str) -> float:
    """Share of the sentence's own tokens that appear in the canonical claim.

    Directional on purpose. A sentence that drops words from the canonical is
    still that claim; a sentence that adds words is making a different one.
    """
    sentence_tokens = tokens(sentence)
    if not sentence_tokens:
        return 0.0
    canonical_tokens = set(tokens(canonical))
    matched = sum(1 for token in sentence_tokens if token in canonical_tokens)
    return matched / len(sentence_tokens)
