# Keyed evals

Everything in this directory needs an API key and is run by hand. None of it
runs in CI, and nothing in the request path depends on it.

## Tier 2 claim adjudication

```bash
ANTHROPIC_API_KEY=... python evals/run_tier2.py
```

Runs the LLM adjudicator over `labelled_sentences.yaml` and prints its
agreement with my labels as a fraction.

The labels are mine, written by hand against `policy/permitted_claims.yaml`.
Where a sentence is genuinely arguable, the `note` field says so rather than
presenting a judgement call as ground truth. About half the set are cases Tier 1
already handles, included so that a Tier 2 which is wrong about something easy
shows up.

**This has not been run.** There is no key in this project and no results are
committed. The script prints what it prints; whatever that turns out to be is
what goes in the README, including if it does badly.
