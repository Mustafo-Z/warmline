#!/usr/bin/env python
"""Run the Tier 2 adjudicator against the labelled set. SPEC 9.3.

    ANTHROPIC_API_KEY=... python evals/run_tier2.py

Never run in CI. Prints agreement as a fraction with the denominator visible,
because a percentage on its own out of twenty items is a way of not saying
twenty.

Whatever this prints is what goes in the README. If it does badly, that is the
number.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from warmline.config import load_claims_config  # noqa: E402
from warmline.postcall.adjudicator import DEFAULT_MODEL, adjudicate  # noqa: E402

LABELLED = Path(__file__).parent / "labelled_sentences.yaml"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    config = load_claims_config()
    cases = yaml.safe_load(LABELLED.read_text())["sentences"]

    agreed = 0
    disagreements = []

    for case in cases:
        result = adjudicate(
            case["text"],
            context="(single sentence, no surrounding turns)",
            config=config,
            model=args.model,
        )
        # A sentence I labelled as no claim at all is agreement if the model
        # calls it permitted: neither of us thinks it needs reporting.
        expected = case["label"]
        if result.verdict == expected:
            agreed += 1
        else:
            disagreements.append((case["text"], expected, result.verdict, result.rationale))

    print(f"model: {args.model}")
    print(f"agreement with my labels: {agreed}/{len(cases)}")
    if disagreements:
        print("\ndisagreements:")
        for text, expected, got, why in disagreements:
            print(f"  {text!r}\n    mine: {expected}  model: {got}\n    model's reason: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
