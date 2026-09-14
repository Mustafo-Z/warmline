# Warmline

An outbound AI voice agent that calls a prospect on behalf of a PR consultancy,
discloses that it is an AI, asks whether they have news worth pitching, and
writes the result back as structured data.

The voice agent is not the subject of this project. The subject is the policy
layer around it: the checks that decide whether a call may be placed at all,
and the checks that verify afterwards whether the agent stayed inside what it
was permitted to say.

Running at **https://warmline.mziyo.com**. The live voice section needs a passcode, sent with the link.

**This build places no telephone calls.** Calls are simulated by replaying
version-controlled conversation scenarios through the same pipeline a real call
would take. No call was placed in the making of this project and no transcript
here came from a real conversation. The reasoning is in
[docs/SPEC.md](docs/SPEC.md) section 2.

## The problem

A PR consultancy earns fees by placing client stories with journalists. Before
that can happen, someone has to find out whether a company has anything worth
pitching right now. Most of that discovery is a short phone call that ends in
"not at the moment", and it consumes the time of the person whose judgement is
the scarce resource.

Automating that first call is not hard. Automating it in a way a listed company
can operate is the whole problem. An agent that says the wrong thing to a real
person is a regulatory and reputational event, not a bug report, and the blast
radius scales with throughput in a way a human caller's does not.

## The policy layer

**Pre-dial.** A call is placed only if nine checks pass: the number is on a
verified allowlist, consent exists and has not expired or been withdrawn, the
number is not suppressed, the declared timezone matches the number's country,
the local time at the destination is inside permitted calling hours, the
per-number attempt limits are not exhausted, and no call is already in flight.
Blocked is the default. Every failure produces a structured reason with an
explanation and, where it applies, the instant at which it would pass.

The engine is a pure function. It reads no database, no clock and no file:
everything is passed in. That is what makes it possible to test the boundary
cases exactly rather than approximately.

**In-call.** The agent's opening utterance is pinned in
[agent/first_turn.md](agent/first_turn.md) and discloses the AI. This is a soft
control and the spec says so: a language model can deviate from a prompt, and a
pinned opening does not constrain turn two.

**Post-call.** The transcript is checked for the disclosure, for claims outside
an allowlist, for commitments the agent has no authority to make, and for an
opt-out the agent failed to honour. Every violation carries the quoted sentence
and the rule that fired, so a reviewer can check the checker.

What the agent may say lives in [policy/permitted_claims.yaml](policy/permitted_claims.yaml)
and the calling rules in [policy/calling_windows.yaml](policy/calling_windows.yaml),
in version control rather than in code or a vendor dashboard, so that changing
what the system is allowed to do arrives as a diff someone can review.

## Running it

Python 3.11+ and Node 20+.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m warmline.storage.seed
.venv/bin/uvicorn warmline.api.main:app --port 8000
```

```bash
cd web && npm install && npm run dev
```

Then open the page the dev server prints. Copy `.env.example` to `.env` if you
want to exercise the webhook; nothing else needs configuration.

**If every row shows "Outside permitted calling hours", the system is working.**
The seed data is in `Asia/Dubai`. Calling hours are 09:00–18:00 Monday to
Thursday and 09:00–12:00 on Friday, with no calling at the weekend — the UAE
working week since 2022, including its half day. Outside those hours the gate
blocks simulated calls exactly as it would block real ones, which is
deliberate: a simulated call is not a way around the policy layer.

To see a completed call outside office hours, widen the window in
`policy/calling_windows.yaml`. That is a policy change and shows up as a diff,
which is the point.

```bash
.venv/bin/python -m pytest        # 182 tests, no keys, no network
.venv/bin/ruff check .
```

## Talking to the live agent

The first section of the page is a real conversation, not a script. Enter the
passcode, allow the microphone, and you are the prospect. The agent is an
ElevenLabs voice agent created from `agent/system_prompt.md` and
`agent/first_turn.md` by `python -m warmline.voice.sync_agent`, so what it was
told is exactly what is in this repository.

It is not an outbound call, and it does not go through the pre-dial gate: you
start it yourself, in your own browser, and no phone number is involved. What it
does go through is everything after the conversation. When it ends, the API
fetches the transcript ElevenLabs stored — not what the page displayed — and
runs the same disclosure, claim, commitment and opt-out checks as every scripted
call. The result is stored labelled `live`, in its own table.

Worth trying: ask what it costs, ask it to promise coverage in a named
publication, ask whether it is a real person, or tell it to stop calling you.

To switch it on for a deployment, put `ELEVENLABS_API_KEY` and
`WARMLINE_VOICE_PASSCODE` in `.env` on the serving machine, run
`python -m warmline.voice.sync_agent`, then re-run `deploy/mac-mini.sh`. Sessions
are capped per hour, each one is limited to the call length in
`agent/agent_config.json`, and the API key never reaches the browser.

## Where this is running

The page is on Vercel. The API runs under launchd on a machine at home, reached
through a Cloudflare tunnel at `warmline-api.mziyo.com` — no port forwarding,
no public IP, and the service binds to localhost so the tunnel is the only way
in. `deploy/mac-mini.sh` sets that up and `deploy/README.md` explains it.

Self-hosted, so it can be briefly unavailable if that machine restarts. Running
it locally takes about a minute and needs nothing but Python and Node.

What you will see depends on when you look, which is the point:

- **Inside UAE calling hours**, the first prospect is callable and the rest each
  block for a different reason — expired consent, withdrawn consent, a
  suppressed number, no consent record, a number that is not on the verified
  allowlist.
- **Outside them**, every row blocks on calling hours as well. A simulated call
  goes through the same gate a real one would; being simulated is not a way
  around the policy layer.
- The attempt limit is one call per number per 24 hours, so a second simulated
  call to the same prospect is refused. That is the limit working, not the
  demo breaking.

## How it is verified

Two tiers, kept apart, because "our evals pass" means nothing if nobody can
tell which ones needed a credit card.

**Deterministic — 182 tests, no API key, no network, runs in CI on every push.**

- The policy engine, tested before it was written. Every consent state, both
  sides of every calling-window boundary including the UAE's Friday half day,
  the same UTC instant allowed in one timezone and blocked in another, DST
  either side of a transition, attempt limits at and around the boundary,
  malformed input, and a combinatorial check that the engine never allows when
  any check blocks.
- The whole scenario library through the real checkers, asserting each scenario
  raises the violations it should **and no others**.
- The agent's own opening line, run through its own disclosure and claim
  checks. It cannot drift out of compliance with the allowlist without the
  build going red.
- API contract tests, including one where the provider double raises if it is
  invoked at all, so a bypassed policy gate fails loudly.

**Keyed — run by hand, never in CI.** The Tier 2 LLM adjudicator over the
sentences the deterministic tier cannot classify, scored against twenty
sentences I labelled myself. See [evals/README.md](evals/README.md).

**This has not been run.** There is no API key in this project, so there is no
number to report. When it is run, whatever it prints goes here, including if it
does badly.

## What is not proven

The live voice section makes the first row of the right-hand column testable:
anyone with the passcode can talk to the real agent and see whether it
discloses, stays inside the allowlist and stops when asked. Testable is not the
same as tested. The ElevenLabs client was built from their API reference and
exercised against a mocked transport; until real sessions have been run and
written up here, that row stays where it is.

The honest cost of simulating rather than calling:

| Proven | Not proven |
|---|---|
| The policy engine blocks and allows correctly, including at boundaries | That a real voice agent obeys the pinned first turn |
| A blocked call never reaches a provider | That the ElevenLabs and Twilio integration works against a live network |
| The post-call checks catch missing disclosure, invented claims, out-of-scope commitments and ignored opt-outs | That they catch what a *real* agent invents, rather than what I scripted it to invent |
| Outcome extraction and write-back | Audio, latency, interruption, accent, line quality |

The right-hand column is the price of the decision. The scripted failures were
written by me, which means they test the checker against my imagination.

Two further gaps, named rather than papered over. The voicemail rule — say
nothing to an answering machine — is instructed in the prompt and is not
verified anywhere, because answering-machine detection is out of scope and a
detector that half worked would be worse than an acknowledged gap. And Tier 1
of the claim checker cannot catch a fluent, novel, paraphrased invented claim
that avoids every pattern; what it can do is report how much it failed to
classify, which a golden file pins so that widening the blind spot turns the
build red.

## How this was built

The implementation was AI-directed. I wrote the brief, made the decisions and
verified the output; Claude wrote the code. Since that is what the role is
about, here is how it actually went.

**The spec came first and nothing else was written until it was settled.**
`docs/SPEC.md` was the entire first commit — the reason codes, the decision
shape, the data model and the API, before any implementation existed to shape
them around. Every open question in it was put to me explicitly rather than
guessed at, and section 11 is a decision log recording what was asked, what I
chose and why, including one decision that superseded an earlier one.

**Tests came before the implementation, visibly.** Commit `739d371` adds 66
policy-engine tests against a stub and is deliberately red; `29704cc` makes it
green. The history is not squashed, so the order of work is legible.

**The spec was corrected when the code proved it wrong.** Writing the engine
showed that `CALL_IN_FLIGHT` is recoverable but has no computable retry time,
and that the config sample was missing a map the timezone check needed. Both
were fixed in the spec in the same commit as the code.

**Directing well meant catching things that looked fine.** The claim checker's
first version rejected the agent's own opening line, because the rule "no
proper nouns" should have been "no proper nouns absent from the canonical
claim" — the canonical contains "AI". The commitment check originally ran
before allowlist matching and flagged "I'll send a calendar invite" as agreeing
to send a document. A non-claim pattern anchored to a prefix rather than the
whole sentence would have dismissed the entire disclosure as a greeting. None
of these would have failed a test that had been written to match the code.

**The most useful correction came from looking at the running system.** Every
prospect was blocking on a Friday, which was correct according to the config
and wrong according to the calendar: the `AE` profile encoded the pre-2022 UAE
working week, which changed to Monday–Friday in January 2022. Fixing it meant
changing the shape of the config, because a half-day Friday cannot be expressed
as one window plus a list of days. Calling windows are now per day. A
compliance layer carrying a four-year-old compliance rule is the specific kind
of wrong this project exists to avoid.

**Running it found what the tests did not.** Two bugs appeared within a minute
of opening the page, both committed with regression tests in `8de7bae`. One
SQLite connection shared across FastAPI's threadpool returned rows with empty
columns under concurrent requests. And the prospect view showed the outcome of
the latest *attempt*, so a completed call disappeared from the table as soon as
the attempt limit started blocking. I confirmed the concurrency test fails
without its fix rather than assuming a passing concurrency test proves
anything.

## What I would do next

Deliberately not built, so the scope stayed finished rather than broad:

- **An LLM outcome extractor.** The current one is keyword matching and is
  labelled as such in the database. It is the weakest component here.
- **Live calls to a verified number**, with the transcripts committed exactly
  as they came back — including the bad ones — to replace the right-hand column
  of the table above with evidence.
- **A retry and scheduling engine.** Calls are triggered one at a time by hand;
  `retry_after` is computed and shown but nothing acts on it.
- **Real DNC register screening**, which the suppression list stands in for.
- **A real-time guard on the model output stream**, so disclosure is enforced
  during the call rather than only verified after it.
- **Per-request connections against a real database.** The single-lock fix is
  right for one user and wrong for many.
- **A retention policy.** Transcripts are kept indefinitely here because they
  are all fictional; that would not survive contact with real data.

## Repository map

```
docs/SPEC.md         the specification, and the decision log
policy/*.yaml        calling windows, verified numbers, claim allowlist, disclosure rule
agent/               system prompt, the pinned opening line, agent config
scenarios/*.json     the scenario library, used by both the tests and the UI
src/warmline/policy  the pre-dial engine: pure functions, no I/O
src/warmline/postcall  transcript normalisation, disclosure and claim checks, extraction
src/warmline/providers  the CallProvider seam; SimulatedProvider is the only one wired
src/warmline/api     FastAPI
tests/               deterministic, no keys
evals/               keyed, manual
web/                 one Next.js page
```

## Regulatory note

I am not a lawyer and this is not legal advice. It is here because a system
like this cannot be designed without knowing which rules it sits beside.

The FCC has ruled that AI-generated voices in unsolicited calls fall within the
TCPA's restrictions on artificial and prerecorded voices, which brings consent,
identification and calling-hour obligations. The UAE restricts unsolicited
marketing calls, with permitted hours and days, company registration and
register checks. The UK's PECR regime carries TPS and CTPS screening
obligations. Recording consent varies by jurisdiction; this project stores no
audio, which removes that surface entirely.

What this models: consent as a record with a lawful basis, suppression,
calling-hours enforcement by destination local time, attempt limits, mandatory
disclosure, and after-the-fact verification. What it does not implement:
national do-not-call register screening, regulator registration, per-
jurisdiction legal review, or data-subject rights workflows.

It is a demonstration, and it should not be pointed at a real prospect list.
