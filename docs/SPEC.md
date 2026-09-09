# Warmline — Specification

| | |
|---|---|
| **Status** | Approved — build against this |
| **Version** | 1.0 |
| **Date** | 2026-09-09 |

Warmline is an outbound AI voice agent that calls a prospect on behalf of a PR
consultancy, discloses that it is an AI, asks whether they have news worth
pitching, and writes the result back as structured data. The subject of this
document is not the voice agent — it is the policy layer around it that decides
whether a call may be placed at all, and that checks afterwards whether the
agent stayed inside what it was permitted to say.

**This build places no telephone calls.** Calls are simulated from
version-controlled conversation scenarios. §2 explains why, and §9 explains what
that does and does not prove.

## Contents

1. [The problem, and who it is for](#1-the-problem-and-who-it-is-for)
2. [Safety constraint and regulatory position](#2-safety-constraint-and-regulatory-position)
3. [Decisions at a glance](#3-decisions-at-a-glance)
4. [The policy layer as a contract](#4-the-policy-layer-as-a-contract)
5. [The permitted-claims allowlist](#5-the-permitted-claims-allowlist)
6. [Data model and API](#6-data-model-and-api)
7. [Explicitly out of scope](#7-explicitly-out-of-scope)
8. [Repository layout and UI scope](#8-repository-layout-and-ui-scope)
9. [How correctness is verified](#9-how-correctness-is-verified)
10. [Build order](#10-build-order)
11. [Decision log](#11-decision-log)

---

## 1. The problem, and who it is for

A PR consultancy earns fees by placing client stories with journalists. Before
any of that can happen, a consultant has to find out whether a company actually
has something worth pitching right now — a funding round, a launch, a hire, a
piece of research, a result. Most of that discovery is a short, low-information
phone call, and most of those calls end in "not at the moment". The consultant's
time is the scarce resource, and it is being spent on the part of the job that
requires the least judgement.

**Warmline** places that first call. It:

1. calls a prospect on a number the consultancy is permitted to call,
2. states in its opening turn that it is an AI calling on behalf of the
   consultancy,
3. asks whether the prospect has news coming up that might be worth pitching,
4. offers a meeting with a human consultant if the answer is interesting,
5. writes the result back to the prospect record as structured data.

The prospect is a business contact — a founder, a marketing lead, a comms
manager — at a company that might become a client. The prospect is *not* a
journalist; Warmline never contacts media.

### 1.1 What this project is actually about

Wiring a voice agent to a phone number is a weekend of plumbing and is not the
interesting part. The interesting part is everything that makes an automated
outbound system safe to operate at a listed company. An agent that says the
wrong thing to a real person is a regulatory and reputational event, not a bug
report — and the blast radius scales with throughput in a way that a human
caller's does not.

So the core of this codebase is a **policy layer the agent cannot bypass**:

- **Pre-dial.** A call is placed only if every check passes. Any failure blocks
  the call and records a structured reason. Blocked is the default.
- **In-call.** The agent must disclose that it is an AI in its opening turn.
- **Post-call.** The transcript is checked: that the disclosure actually
  happened, and that the agent made no claim outside an allowlist of permitted
  statements. Violations are flagged on the record.

The policy engine is the best-tested code in the repository, and it is written
first.

---

## 2. Safety constraint and regulatory position

**This is a demonstration. It is not a deployable outbound calling system, and
it must not be pointed at a real prospect list.**

### 2.1 Nothing dials

This build never contacts a telephone network. Calls are **simulated**: a
`SimulatedProvider` resolves a named, version-controlled conversation scenario
into a transcript and hands it to exactly the same post-call pipeline a real
call would use (§6.3).

That is a deliberate choice, not a shortcut, and it is worth being precise about
what it buys and what it costs.

- **What it buys.** The regulatory surface of running this project is zero. No
  consent question, no calling-hours question, no recording question, no chance
  of an AI voice reaching someone who did not agree to it. It also means the
  post-call checks run in CI on every commit rather than only when someone picks
  up a phone, so the evidence base is *larger* than it would be with a handful
  of live calls.
- **What it costs.** The provider integration is never exercised against a real
  network, and no transcript in this repository came from a real conversation. A
  scripted scenario cannot surprise the checker the way a real person can. §9.2
  states this plainly rather than leaving a reviewer to work it out.

The design still carries the controls a dialling version would need, because
they are the substance of the project:

| Layer | Control | Status in this build |
|---|---|---|
| Code path | No wired code path reaches a phone network. `ElevenLabsProvider` is written to the provider interface and is never instantiated. | Active |
| Policy engine | `NUMBER_NOT_VERIFIED` — the destination must appear in a version-controlled allowlist of owner-verified numbers or the call is blocked before any provider is called. | Active, and runs on simulated calls too |
| Platform | Twilio **trial** account, which itself refuses to connect a call to a number not verified on the account. | Designed, not exercised |
| Data | Seed prospects are fictional, flagged `is_fixture = true`, and shown as fictional in the UI. | Active |

If this were ever pointed at a network, the rule would be: only numbers I own,
or numbers whose owner explicitly agreed in advance to a test call. No purchased
lists, no scraped numbers, no enrichment vendors, no real prospect data.

### 2.2 Regulatory context

I am not a lawyer and this is not legal advice. It is here because a system like
this cannot be designed without knowing which rules it sits next to.

- **AI voices in unsolicited calls (US).** The FCC has ruled that AI-generated
  voices in unsolicited calls fall within the TCPA's restrictions on artificial
  or prerecorded voices: prior express consent is required, and the usual
  identification and opt-out obligations apply. Calling hours are constrained
  (commonly cited as 8am–9pm local to the called party).
- **Telemarketing (UAE).** The UAE's telemarketing regime restricts unsolicited
  marketing calls, sets permitted calling hours and days, requires company
  registration and register checks, and requires calls to be made from
  registered numbers. A production version operating into the UAE would need a
  compliance workflow this project does not implement.
- **Marketing calls (UK).** PECR and the ICO's direct-marketing guidance govern
  unsolicited marketing calls, with TPS/CTPS screening obligations this project
  does not implement.
- **Recording consent.** Two-party-consent jurisdictions require notice and
  sometimes consent before recording. This project stores **no call audio**
  (§7), which removes the recording-consent surface entirely. Transcripts are
  stored.

What this project models: consent as a first-class record with a lawful basis,
suppression, calling-hours enforcement by destination local time, attempt
limits, mandatory AI disclosure, and after-the-fact verification that the
disclosure and content rules held. What it does **not** implement: national
do-not-call register screening, regulator registration, per-jurisdiction legal
review, or data-subject rights workflows.

---

## 3. Decisions at a glance

Every decision below was taken by the human directing this project. The question
as it was put, the answer, and the reasoning are in the [decision log](#11-decision-log).

| Decision | Value | Specified in |
|---|---|---|
| Calls are simulated | Scripted scenarios replayed through the full pipeline; nothing dials | §2.1, §6.3, §9.2 |
| Dial path | Built behind a `CallProvider` seam; `SimulatedProvider` wired, `ElevenLabsProvider` written and unwired | §6.3 |
| Claim check | Layered — Tier 1 deterministic in CI, Tier 2 LLM adjudicator keyed and manual | §5.2, §9.3 |
| Calling hours | IANA timezone on the prospect + per-region window config; E.164 prefix cross-checked | §4.2 |
| Default region | `AE`; seed data is UAE, `UK` and `US` profiles exercised by tests | §4.2 |
| Consent | A record with lawful basis, timestamps and evidence — not a boolean | §4.2, §6.2 |
| Consent expiry | 180 days from capture; one seed prospect seeded already-expired | §6.2 |
| Attempt limits | 1 per 24h, 3 per rolling 7 days; only calls that reached a provider count | §4.2 |
| Timezone/prefix mismatch | Blocks (configurable to `warn`; both paths tested) | §4.2 |
| Consultancy | Meridian Communications — fictional | §5.1 |
| Opening line | Pinned, discloses the AI, names the principal, offers an out in turn one | §4.4 |
| Voicemail | Agent says nothing and ends the call | §4.4 |
| Transcript retention | Indefinite in this build; named as a real-deployment gap | §7 |
| UI | One page, plus a per-row dry-run "why is this blocked?" button | §8 |

---

## 4. The policy layer as a contract

### 4.1 Shape of the contract

The pre-dial engine is a **pure function**:

```
evaluate_pre_dial(request: PreDialRequest, config: PolicyConfig) -> PolicyDecision
```

Contract:

- **No I/O.** No database access, no network, no file reads, no clock reads. The
  current instant, the attempt history, the suppression entries and the config
  are all passed in by the caller. This is what makes the boundary tests in §9.1
  possible.
- **Total.** Every input, including malformed input, produces a `PolicyDecision`.
  It never raises for bad data; bad data is a block reason.
- **Fail closed.** `decision` is `"block"` unless every check returns `pass`. A
  check that cannot be evaluated returns `block`, not `pass`.
- **Complete.** All checks are evaluated; the engine does not short-circuit on
  the first failure. A prospect that fails three checks reports three failures,
  because someone who fixes one and retries should not discover the other two
  one call at a time.
- **Deterministic ordering.** `primary_reason` is chosen by a fixed severity
  order defined in config, not by evaluation order or dict iteration order.

### 4.2 Pre-dial checks

Evaluated in the order listed. All of them run, on simulated calls exactly as on
real ones.

| # | Code | Inputs | Blocks when | Recoverable |
|---|---|---|---|---|
| 1 | `NUMBER_NOT_VERIFIED` | `phone_e164`, verified-number allowlist | the destination is not in the owner-verified allowlist | `never` |
| 2 | `CONSENT_MISSING` | consent record | no consent record exists | `on_data_fix` |
| 3 | `CONSENT_EXPIRED` | `consent.expires_at`, `now` | `expires_at` is set and `expires_at <= now` | `on_data_fix` |
| 4 | `CONSENT_WITHDRAWN` | `consent.withdrawn_at` | `withdrawn_at` is set | `never` |
| 5 | `NUMBER_SUPPRESSED` | `phone_e164`, suppression list | the normalised number is in the suppression list | `never` |
| 6 | `TIMEZONE_PREFIX_MISMATCH` | E.164 prefix, `prospect.timezone` | the country implied by the prefix is not a country the declared timezone belongs to | `on_data_fix` |
| 7 | `OUTSIDE_CALLING_HOURS` | `timezone`, `region_profile`, window config, `now` | local wall-clock time is outside the window, or the local day is not permitted | `after` |
| 8 | `ATTEMPT_LIMIT_REACHED` | attempt history, limits config | the per-24h or per-rolling-7d cap is met or exceeded | `after` |
| 9 | `CALL_IN_FLIGHT` | attempt history | an attempt for this prospect is `dialing` or `in_progress` | `after` |
| — | `CHECK_NOT_EVALUABLE` | any | a check could not be evaluated — unparseable timezone, malformed E.164, missing config profile | `on_data_fix` |

**`NUMBER_NOT_VERIFIED`** reads `policy/verified_numbers.yaml`, a
version-controlled list of E.164 numbers with `owner` and `agreed_at`. It is the
§2.1 constraint expressed as code. It is check #1 and the highest-severity
reason, so a run against an accidental real list blocks on the right reason
rather than on calling hours.

**Consent** is a record, not a flag. The three failure modes are distinct
because they mean different things operationally: missing is a data gap, expired
is a refresh job, withdrawn is permanent and must never be "fixed" by re-adding
consent.

**`NUMBER_SUPPRESSED`** matches on the E.164-normalised number, so
`+971 50 123 4567` and `+971501234567` are the same entry. The suppression
entry's own reason is echoed into the check detail, so the UI can say *why*
without a second lookup.

**`TIMEZONE_PREFIX_MISMATCH`** exists because "local time at the destination" is
only as good as the timezone field. A `+1` number carrying `Asia/Dubai` is a
data error that would otherwise silently produce calls at 3am. It **blocks**:
the fix is a one-field edit, so blocking costs little, and a data error that
defeats the hours check should not be survivable. `warn` is available in config
and both settings are covered by tests.

**`OUTSIDE_CALLING_HOURS`** converts `now` (a UTC instant) to the prospect's
IANA timezone and compares local wall-clock time against the window for the
prospect's region profile. Window semantics are **half-open, `[start, end)`**:
with a `09:00–18:00` window, `09:00:00` local is allowed and `18:00:00` local is
blocked. This is stated because it is the single most likely place for the
implementation and the tests to disagree silently.

`policy/calling_windows.yaml`:

```yaml
policy_version: "1.0.0"
default_profile: AE
profiles:
  AE:
    countries: [AE]
    days: [sun, mon, tue, wed, thu]
    window: { start: "09:00", end: "18:00" }
  UK:
    countries: [GB]
    days: [mon, tue, wed, thu, fri]
    window: { start: "09:00", end: "18:00" }
  US:
    countries: [US, CA]
    days: [mon, tue, wed, thu, fri]
    window: { start: "09:00", end: "20:00" }

# What TIMEZONE_PREFIX_MISMATCH does when it fires.
timezone_mismatch_action: block

# Countries each supported timezone belongs to, used by
# TIMEZONE_PREFIX_MISMATCH. Hand-maintained on purpose: this is
# policy-relevant geography, so it belongs in a file a reviewer can diff
# rather than inside a dependency. A timezone absent from this map is not
# trusted — the check returns CHECK_NOT_EVALUABLE, which blocks.
timezone_countries:
  Asia/Dubai: [AE]
  Europe/London: [GB]
  America/New_York: [US]
  America/Los_Angeles: [US]
  # ... and the other supported zones
```

`AE` is the default and the profile the seed data uses, because that is the
market the demo is written for. `UK` and `US` exist so the timezone logic is
proven against more than one window, and they are exercised by the tests in
§9.1 rather than by seed data.

DST is handled by converting the instant to local time via `zoneinfo`, which is
always well defined in that direction; the ambiguous-local-time problem does not
arise because we never parse a local wall-clock time into an instant. Public
holidays are out of scope (§7).

**`ATTEMPT_LIMIT_REACHED`** counts attempts against the *number*, not the
prospect record, so two prospect rows sharing a number cannot double the budget.
Only attempts that reached a provider count — a call blocked at pre-dial does
not consume budget.

```yaml
attempt_limits:
  max_per_24h: 1
  max_per_rolling_7d: 3
```

These are deliberately tight. A limit that never fires during a demo is a limit
nobody can see working.

**`CALL_IN_FLIGHT`** is a concurrency guard, not a compliance rule. Two clicks
of the call button should produce one call and one clear "already dialling"
response.

### 4.3 The emitted decision

Every evaluation produces this shape. It is stored verbatim on the attempt and
returned verbatim by the API — the UI, the tests and the audit trail all read
the same object.

```json
{
  "decision": "block",
  "policy_version": "1.0.0",
  "config_digest": "sha256:1f0c…",
  "evaluated_at": "2026-09-09T05:14:22Z",
  "prospect_id": "psp_0003",
  "phone_e164": "+971501234567",
  "primary_reason": "OUTSIDE_CALLING_HOURS",
  "blocking_reasons": ["OUTSIDE_CALLING_HOURS", "ATTEMPT_LIMIT_REACHED"],
  "checks": [
    {
      "code": "NUMBER_NOT_VERIFIED",
      "result": "pass",
      "detail": { "matched_owner": "self" }
    },
    {
      "code": "OUTSIDE_CALLING_HOURS",
      "result": "block",
      "message": "Local time 06:14 in Asia/Dubai is outside the AE window 09:00-18:00.",
      "recoverable": "after",
      "retry_after": "2026-09-09T05:00:00Z",
      "detail": {
        "timezone": "Asia/Dubai",
        "local_time": "2026-09-09T09:14:22+04:00",
        "local_day": "wed",
        "profile": "AE",
        "window": { "start": "09:00", "end": "18:00" },
        "permitted_days": ["sun", "mon", "tue", "wed", "thu"]
      }
    },
    {
      "code": "ATTEMPT_LIMIT_REACHED",
      "result": "block",
      "message": "1 attempt in the last 24h; limit is 1.",
      "recoverable": "after",
      "retry_after": "2026-09-10T04:02:11Z",
      "detail": {
        "attempts_24h": 1, "limit_24h": 1,
        "attempts_7d": 1, "limit_7d": 3,
        "last_attempt_at": "2026-09-09T04:02:11Z"
      }
    }
  ]
}
```

Field rules:

- `result` is `pass` | `block` | `warn`. There is no `skip`; a check that cannot
  run emits `CHECK_NOT_EVALUABLE` with `result: "block"`.
- `warn` never contributes to `blocking_reasons` and never changes `decision`.
- `recoverable` is `never` | `on_data_fix` | `after`. When it is `after`,
  `retry_after` carries the earliest instant at which that specific check would
  pass, computed from the same inputs. This is what lets the UI say "blocked
  until 09:00 Asia/Dubai" rather than just "blocked". `CALL_IN_FLIGHT` is the
  one exception: it is recoverable, but the unblocking event is the call
  ending rather than a clock time, so its `retry_after` is null.
- `message` is human-readable and safe to show in a UI. It never contains the
  full phone number.
- `config_digest` is the SHA-256 of the concatenated policy config files, so a
  stored decision can be re-evaluated against the exact config that produced it,
  and a decision made under an older policy version is distinguishable from a
  current one.
- Severity order for `primary_reason`, fixed in config:
  `NUMBER_NOT_VERIFIED` → `CONSENT_WITHDRAWN` → `NUMBER_SUPPRESSED` →
  `CONSENT_MISSING` → `CONSENT_EXPIRED` → `TIMEZONE_PREFIX_MISMATCH` →
  `CHECK_NOT_EVALUABLE` → `ATTEMPT_LIMIT_REACHED` → `OUTSIDE_CALLING_HOURS` →
  `CALL_IN_FLIGHT`. Permanent blocks outrank recoverable ones, so the reason
  shown to a human is the one that needs a human.

### 4.4 In-call: disclosure and voicemail

**The opening turn is pinned.** The agent's first utterance is fixed in
`agent/first_turn.md` rather than composed by the model:

> Hi, I'm an AI assistant calling on behalf of Meridian Communications. I'll
> keep this under a minute. Is now an okay time?

Three sentences, deliberately. It discloses the AI and names the principal in
the first, makes its one commitment in the second, and hands control to the
prospect in the third. It is punctuated as three sentences rather than joined
with a dash so that the sentence segmenter in §5.2 sees the commitment
("I'll keep this under a minute") as its own sentence and checks it against the
allowlist, instead of letting it ride along inside a question and escape review.
The opening line is checked against its own allowlist in CI (§9.1).

**Voicemail: the agent must not speak to a machine.** If it reaches an answering
machine or voicemail greeting, it says nothing and ends the call. Leaving an
AI-voice message on someone's phone is the riskiest single thing this system
could do, and machine detection is unreliable enough that silence is the correct
default.

**Both of these are soft controls, and I want to be plain about that.** They are
instructions in a version-controlled prompt and a pinned first utterance. A
language model can deviate from a prompt, and a pinned opening does not
constrain turn two. Disclosure is *instructed* at runtime and **verified after
the fact** (§4.5), with the violation recorded and surfaced in the UI. The
voicemail rule is instructed and **not independently verified at all** — see §7,
where that gap is named rather than papered over with a detector that would only
half work.

### 4.5 Post-call checks

| Code | Detects | Side effect |
|---|---|---|
| `DISCLOSURE_MISSING` | no accepted disclosure phrasing anywhere in the agent's turns | flag on outcome |
| `DISCLOSURE_NOT_IN_FIRST_TURN` | disclosure present, but not in the first agent turn | flag on outcome |
| `UNPERMITTED_CLAIM` | an agent sentence asserts something outside the allowlist (§5) | flag on outcome, one per sentence, with quote |
| `OUT_OF_SCOPE_COMMITMENT` | the agent agreed to something it cannot commit to — pricing, discounts, guaranteed coverage, contractual terms, sending documents, deadlines | flag on outcome, with quote |
| `OPT_OUT_NOT_HONOURED` | the prospect asked to stop, and the agent continued to pitch or did not acknowledge | flag on outcome **and** write a suppression entry |

Two rules across all of them:

1. **Every violation carries evidence** — the exact quoted sentence, the turn
   index, and the rule or pattern id that fired. A reviewer must be able to
   check the checker without re-reading the transcript.
2. **Opt-out is honoured regardless of whether the agent handled it.** If the
   detector sees an opt-out request in the prospect's turns, the number is
   suppressed. `OPT_OUT_NOT_HONOURED` is about whether the *agent* behaved; the
   suppression happens either way.

---

## 5. The permitted-claims allowlist

### 5.1 Where it lives

`policy/permitted_claims.yaml` and `policy/disclosure.yaml`, in version control
— not inline in Python, and not only in a provider dashboard. The point of the
exercise is that the rules are reviewable in a diff and testable in CI.

```yaml
policy_version: "1.0.0"
principal: "Meridian Communications"   # fictional consultancy

disclosure:
  required_in_agent_turn: 1            # the first agent turn; transcript index 0
  accepted_patterns:
    - "i'?m an ai (assistant|agent|voice assistant)"
    - "this is an (automated|ai) call"
  must_also_mention_principal: true

permitted_claims:
  - id: WHO_WE_ARE
    canonical: "Hi, I'm an AI assistant calling on behalf of Meridian Communications."
    may_paraphrase: true
  - id: TIME_PROMISE
    canonical: "I'll keep this under a minute."
    may_paraphrase: true
  - id: WHY_CALLING
    canonical: "We work with companies on press coverage, and I'm calling to ask whether you have any news coming up."
    may_paraphrase: true
  - id: WHAT_HAPPENS_NEXT
    canonical: "If it sounds relevant, I can book a short call with one of our consultants."
    may_paraphrase: true
  - id: HOW_WE_GOT_NUMBER
    canonical: "You're on our list because you agreed to be contacted about this."
    may_paraphrase: false
  - id: OPT_OUT
    canonical: "If you'd rather we didn't call again, I'll make sure we don't."
    may_paraphrase: true

prohibited_patterns:
  - id: PRICE
    pattern: '(\$|£|€|AED|USD|GBP)\s?\d|(\d+\s?(dollars|pounds|dirhams))'
    reason: "The agent may not discuss price."
  - id: GUARANTEE
    pattern: '\b(guarantee|guaranteed|we can promise|definitely will)\b'
  - id: NAMED_OUTLET
    pattern: '\b(the times|forbes|techcrunch|financial times|bbc|bloomberg|reuters)\b'
    reason: "The agent may not name outlets it can place a story in."
  - id: TIMELINE
    pattern: '\b(within \d+ (days|weeks)|by (next|the end of) (week|month))\b'
  - id: COVERAGE_PROMISE
    pattern: '\b(get you (coverage|featured|published|in the press))\b'
  - id: COMPETITOR
    pattern: '\b(better than|cheaper than|unlike)\b.{0,40}\b(agency|agencies|competitor)\b'

# Non-claim patterns are anchored to the WHOLE sentence, and a sentence is only
# ELIGIBLE to be a non-claim if it carries no numeric token and no proper noun
# other than the principal. Numbers and names are the raw material of invented
# claims, so a sentence containing either is always checked against the
# allowlist -- even if it is phrased as a question.
non_claim_eligibility:
  no_numeric_tokens: true
  no_proper_nouns_except_principal: true

non_claim_patterns:
  - id: GREETING
    pattern: '^(hi|hello|good (morning|afternoon|evening))[.,!]?$'
  - id: ACKNOWLEDGEMENT
    pattern: '^(thanks|thank you|sure|of course|no problem|great|understood|got it)[.,!]?$'
  - id: QUESTION
    pattern: '^[^.!]*\?$'
  - id: SCHEDULING
    pattern: '^(what time works|does .* work for you|i can put that in the calendar|i.ll send a calendar invite)[.?!]?$'
```

### 5.2 How a violation is detected

Input is a normalised transcript (§6.2). The pipeline runs over **agent turns
only**; what the prospect says is evidence, never a violation.

```
agent turns
  → sentence segmentation (deterministic splitter on . ? !, no ML)
  → Tier 1a: prohibited-pattern scan
  → Tier 1b: classify remainder as non-claim / permitted-match / unclassified
  → Tier 2: LLM adjudication of `unclassified` only        [keyed, manual only]
```

**Tier 1a — prohibited patterns.** Any sentence matching a `prohibited_patterns`
entry is an `UNPERMITTED_CLAIM` immediately, recorded with the pattern id and
the quoted sentence. No further classification is attempted for that sentence.
This tier is a blunt instrument by design: it catches the specific things the
agent must never say, with no ambiguity and no model in the loop.

**Tier 1b — allowlist matching.** Each remaining sentence is classified as:

- `non_claim` if it carries no numeric token and no proper noun other than the
  principal, **and** matches a `non_claim_patterns` entry **in full**. Both
  conditions were added after testing the rules against the agent's own opening
  line. Anchoring to the whole sentence stops a prefix match dismissing "Hi,
  I'm an AI assistant calling on behalf of Meridian Communications" as a
  greeting. The numeric and proper-noun guard stops an assertion escaping
  review by ending in a question mark: without it, "We work with 400 companies,
  do you have news?" classifies as a harmless question and the invented figure
  is never checked. With it, the sentence falls through to `unclassified` and
  is reported.
- `permitted` if it matches a permitted claim: normalised token overlap with the
  canonical statement at or above a configured threshold, **and** the sentence
  introduces no numeric token, proper noun, or superlative absent from the
  canonical. The second condition is what stops "we work with companies on press
  coverage" and "we work with 400 companies on press coverage" from being
  treated as the same claim.
- `unclassified` otherwise.

**Tier 2 — LLM adjudication.** For the `unclassified` residue only, an LLM judge
receives the sentence, its surrounding turns, and the full allowlist, and
returns either a matching `claim_id` or `UNPERMITTED` with a one-line rationale
and the quote. Model configurable, defaulting to `claude-sonnet-5`.

Two constraints on Tier 2, both of which matter:

- **It never runs in CI.** It requires a key and is run manually (§9.3).
- **It can only add violations, never clear one.** A Tier 1a match is final. The
  adjudicator is itself an LLM and can be wrong; giving a model the power to
  dismiss a deterministic compliance finding would put the least reliable
  component in the most consequential position.

**What Tier 1 alone does and does not do.** Tier 1 catches every violation in
the committed scenario library (§9.2), and CI asserts that. It will not catch a
fluent, novel, paraphrased invented claim that avoids every prohibited pattern —
nothing deterministic will. The `unclassified` count is therefore itself a
reported signal: the tests assert the exact set of unclassified sentences
against a golden file, so a pattern change that quietly widens the blind spot
fails the build.

---

## 6. Data model and API

### 6.1 Storage

SQLite, one file, schema created by a versioned migration. Timestamps are stored
as UTC ISO-8601 strings. Phone numbers are stored E.164-normalised, and the
normalisation function is shared by storage, the policy engine and the
suppression list.

### 6.2 Tables

**`prospect`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | `psp_0001` |
| `full_name` | TEXT NOT NULL | fictional in seed data |
| `company` | TEXT NOT NULL | fictional in seed data |
| `role` | TEXT NULL | |
| `phone_e164` | TEXT NOT NULL | normalised |
| `timezone` | TEXT NOT NULL | IANA, e.g. `Asia/Dubai` |
| `region_profile` | TEXT NOT NULL | key into `calling_windows.yaml`; `AE` for all seed data |
| `language` | TEXT NOT NULL | `en`; other values out of scope |
| `is_fixture` | INTEGER NOT NULL | `1` for all seed data |
| `created_at` / `updated_at` | TEXT NOT NULL | |

**`consent`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | |
| `prospect_id` | TEXT FK NOT NULL | |
| `lawful_basis` | TEXT NOT NULL | `explicit_opt_in` \| `existing_client` \| `test_number_owner_agreement` |
| `captured_at` | TEXT NOT NULL | |
| `expires_at` | TEXT NULL | seeded at `captured_at + 180 days` |
| `evidence` | TEXT NOT NULL | free text, e.g. "fictional seed record — no real person" |
| `withdrawn_at` | TEXT NULL | set on opt-out; never cleared |
| `created_at` | TEXT NOT NULL | |

Consent expires 180 days after capture. Seed data includes **one prospect whose
consent is already expired** and **one whose consent is withdrawn**, so
`CONSENT_EXPIRED` and `CONSENT_WITHDRAWN` are visible in the UI on first run
rather than living only in the test suite.

**`suppression_entry`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | |
| `phone_e164` | TEXT NOT NULL UNIQUE | |
| `reason` | TEXT NOT NULL | `do_not_call` \| `complaint` \| `wrong_number` \| `manual` \| `opt_out_in_call` |
| `source` | TEXT NOT NULL | `seed` \| `api` \| `post_call` |
| `note` | TEXT NULL | |
| `created_at` | TEXT NOT NULL | |

**`policy_evaluation`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | |
| `prospect_id` | TEXT FK NOT NULL | |
| `phase` | TEXT NOT NULL | `pre_dial` \| `post_call` |
| `decision` | TEXT NOT NULL | `allow` \| `block` |
| `primary_reason` | TEXT NULL | null when `allow` |
| `checks_json` | TEXT NOT NULL | the object from §4.3, stored verbatim |
| `policy_version` | TEXT NOT NULL | |
| `config_digest` | TEXT NOT NULL | |
| `evaluated_at` | TEXT NOT NULL | |

**`call_attempt`**

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | `att_0001` |
| `prospect_id` | TEXT FK NOT NULL | |
| `phone_e164` | TEXT NOT NULL | snapshot at dial time |
| `status` | TEXT NOT NULL | `blocked` \| `dialing` \| `in_progress` \| `completed` \| `no_answer` \| `failed` |
| `policy_evaluation_id` | TEXT FK NOT NULL | every attempt, including blocked ones, has one |
| `provider` | TEXT NOT NULL | `simulated` \| `elevenlabs` |
| `scenario` | TEXT NULL | scenario id, when `provider = simulated` |
| `provider_conversation_id` | TEXT NULL | |
| `provider_call_sid` | TEXT NULL | |
| `requested_at` | TEXT NOT NULL | |
| `dialed_at` | TEXT NULL | null for blocked attempts |
| `ended_at` | TEXT NULL | |
| `duration_seconds` | INTEGER NULL | |
| `error` | TEXT NULL | provider error, verbatim |

A blocked call is still a `call_attempt` row with `status = blocked` and
`dialed_at = null`. Blocks are records, not absences of records — otherwise the
system cannot answer "how often does policy stop us, and why", which is the
first question anyone senior will ask of it.

**`call_outcome`** — one row per completed attempt.

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | |
| `call_attempt_id` | TEXT FK NOT NULL UNIQUE | |
| `transcript_json` | TEXT NOT NULL | normalised transcript, stored verbatim |
| `transcript_source` | TEXT NOT NULL | `scenario` \| `live` |
| `disclosure_ok` | INTEGER NOT NULL | |
| `violations_json` | TEXT NOT NULL | list of `{code, rule_id, turn_index, quote, tier}` |
| `has_news` | INTEGER NULL | |
| `news_summary` | TEXT NULL | |
| `interest` | TEXT NOT NULL | `interested` \| `not_interested` \| `callback_later` \| `unclear` |
| `meeting_requested` | INTEGER NOT NULL | |
| `meeting_preferences` | TEXT NULL | free text as stated by the prospect |
| `opt_out_requested` | INTEGER NOT NULL | |
| `extraction_method` | TEXT NOT NULL | `deterministic` \| `llm` |
| `processed_at` | TEXT NOT NULL | |
| `review_status` | TEXT NOT NULL | `unreviewed` \| `human_ok` \| `human_flagged` |

**Normalised transcript** — the shape every checker consumes, so that scenario
transcripts and any future live transcript are indistinguishable to the code:

```json
{
  "conversation_id": "sim_missing_disclosure_001",
  "source": "scenario",
  "turns": [
    { "index": 0, "role": "agent",    "text": "Hi, I'm an AI assistant calling on behalf of Meridian Communications. I'll keep this under a minute. Is now an okay time?" },
    { "index": 1, "role": "prospect", "text": "Go on then." }
  ]
}
```

`source` is `scenario` | `live`, and it is set by the loader, not by the
transcript author. It is carried through to `call_outcome.transcript_source` and
shown in the UI, so **no scripted conversation can ever be presented as a real
call** — not in the database, not in the interface, not by accident.

### 6.3 Call flow and the provider seam

One interface, two implementations, one post-call path:

```
CallProvider (protocol)
  ├── SimulatedProvider   — wired. Resolves a scenario id to a transcript.
  └── ElevenLabsProvider  — written to the same seam, never instantiated.
```

```
POST /prospects/{id}/calls
  → load prospect, consent, suppression entries, attempt history
  → evaluate_pre_dial(...)              pure, no I/O
  → persist policy_evaluation
  → if block: persist call_attempt(status=blocked); return 409 with the decision
  → if allow: persist call_attempt(status=dialing)
  → provider.place_call(...)
        ├── simulated:   returns the scenario transcript immediately
        └── elevenlabs:  returns a conversation id; transcript arrives by webhook
  → process_post_call(transcript)       ← one entry point, both providers
        → normalise transcript
        → disclosure check, claim check Tier 1, outcome extraction
        → persist call_outcome, update call_attempt
        → if opt-out detected: write suppression_entry
```

Three properties this seam is built to give:

1. **The policy gate runs first, always.** A simulated call is blocked by policy
   exactly as a real one would be. There is no "it's only a simulation" branch —
   the demo cannot dial a suppressed number any more than production could.
2. **The post-call pipeline has one entry point.** `process_post_call` does not
   know or care which provider produced the transcript, so every check exercised
   by a scenario is the same code a real call would go through.
3. **There is exactly one function that can initiate a dial**, and its only
   caller is the branch above.

### 6.4 API surface

All responses are JSON. No authentication (§7). The active provider comes from
config (`CALL_PROVIDER=simulated`).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | liveness |
| `GET` | `/prospects` | list with latest attempt, latest outcome, latest block reason |
| `GET` | `/prospects/{id}` | one prospect with full attempt history |
| `POST` | `/prospects/{id}/policy-check` | evaluate pre-dial policy and return the decision **without dialling** |
| `POST` | `/prospects/{id}/calls` | policy-gated call |
| `GET` | `/calls/{attempt_id}` | attempt, its policy evaluation, its outcome |
| `GET` | `/scenarios` | the scenario library, for the UI's scenario picker |
| `GET` | `/suppressions` | list |
| `POST` | `/suppressions` | add a number |

**`POST /prospects/{id}/policy-check`**

`as_of` allows evaluating the policy at a hypothetical instant, which is how the
UI answers "when will this be callable?" and how the tests exercise time without
mocking a clock.

```json
{ "as_of": "2026-09-09T05:14:22Z" }
```

Response `200` — the `PolicyDecision` object from §4.3, unchanged. A `block`
here is a successful request, not an error: nothing was attempted.

**`POST /prospects/{id}/calls`**

```json
{ "scenario": "invented_pricing_claim" }
```

`scenario` is required when the provider is `simulated` and ignored otherwise.

`202 Accepted` when the policy allows and the provider accepted:

```json
{
  "attempt_id": "att_0007",
  "status": "completed",
  "policy": { "decision": "allow", "…": "…" },
  "provider": { "name": "simulated", "conversation_id": "sim_invented_pricing_claim_001" },
  "outcome_id": "out_0007"
}
```

`409 Conflict` when the policy blocks. The full decision is the body — the
caller never has to make a second request to find out why:

```json
{
  "error": "policy_blocked",
  "attempt_id": "att_0008",
  "policy": { "decision": "block", "primary_reason": "NUMBER_SUPPRESSED", "…": "…" }
}
```

`502 Bad Gateway` when the policy allowed but the provider failed. The attempt
is recorded with `status = failed` and the error stored verbatim. A provider
failure is never reported as a policy block, and a policy block is never
reported as a provider failure.

**`POST /webhooks/elevenlabs/post-call`** is specified but not mounted in this
build, since nothing dials. When mounted, it verifies the provider's HMAC
signature over the raw body before parsing; an unverified request is rejected
`401` and nothing is written; a replayed `conversation_id` is acknowledged `200`
and ignored, so a provider retry cannot produce two outcomes.

---

## 7. Explicitly out of scope

Named here so that neither I nor the agents building this quietly add them.
Anything I think of later goes in the README's "What I would do next".

- **Real telephony.** Nothing dials. `ElevenLabsProvider` is written to the
  provider seam and never instantiated; the Twilio account, the webhook mount
  and the media path are designed but not exercised.
- **Answering-machine detection.** The agent is instructed not to speak to a
  machine (§4.4). That instruction is **not independently verified** — there is
  no detector asserting it held. This is a deliberate choice: AMD is out of
  scope, and a half-working detector would be worse than a named gap in a
  document whose whole argument is that soft controls get verified properly or
  not at all.
- **Retry and scheduling.** No queue, no cron, no automatic retry after a
  calling-hours block. Calls are triggered one at a time from the UI.
- **Real calendar booking.** Meeting interest and stated preferences are
  captured as structured data. Nothing is written to a calendar.
- **Authentication, authorisation, multi-tenancy.** Single-user, local,
  unauthenticated.
- **CRM integration.** SQLite is the system of record.
- **National DNC / TPS / CTPS register screening.** The suppression list is
  local only.
- **Audio.** No recording, no storage, no playback. Transcripts only.
- **Transcript retention limits.** Transcripts are kept indefinitely. Every one
  of them is a scripted scenario, so there is no third-party data to age out —
  but a real deployment needs a retention policy, and this build does not model
  one.
- **Public-holiday calendars** in the calling-hours check.
- **Other channels.** No SMS, WhatsApp, or email.
- **Languages other than English.**
- **Real-time guardrails on the model output stream.** Disclosure and claim
  compliance are verified after the call, not enforced during it (§4.4).
- **Scale, concurrency, rate limiting, provider failover.**

---

## 8. Repository layout and UI scope

```
docs/SPEC.md
policy/
  calling_windows.yaml
  permitted_claims.yaml
  disclosure.yaml
  verified_numbers.yaml
agent/
  system_prompt.md             # version-controlled
  first_turn.md                # the pinned disclosure opening
  agent_config.json
scenarios/                     # the scenario library — one source of truth,
  compliant_meeting_booked.json    # used by both the CI tests and the UI
  compliant_not_interested.json
  missing_disclosure.json
  invented_pricing_claim.json
  out_of_scope_agreement.json
  prospect_opts_out.json
src/warmline/
  policy/                      # pure functions, no I/O
  storage/
  providers/                   # CallProvider, SimulatedProvider, ElevenLabsProvider
  postcall/                    # normalisation, checks, extraction
  api/
tests/                         # deterministic, no keys
evals/                         # keyed, manual
web/                           # Next.js, one page, built last
```

**UI scope — one page, and it is built last.** A prospect table where each row
shows the prospect, the last outcome, and the last policy block reason in plain
language. Two buttons per row:

- **Check policy** — calls `POST /prospects/{id}/policy-check` and shows the
  decision without doing anything. This is the cheapest way to show the policy
  layer to someone who is not going to read the test suite.
- **Simulate call** — picks a scenario and calls `POST /prospects/{id}/calls`.

No auth, no state library, minimal styling. Rows sourced from a scenario are
labelled as simulated in the interface. If the UI starts eating time, it stops
and the service ships without it: a finished service with excellent tests beats
a broken full-stack app.

---

## 9. How correctness is verified

Three tiers, hard separated, because "our evals pass" means nothing if nobody
can tell which ones needed a credit card.

### 9.1 Deterministic — runs in CI, no API keys, no network

**Policy engine.** Tests are written before the implementation. Every case below
is a named test:

- missing consent; consent expired exactly at `expires_at`; expired one second
  later; consent withdrawn
- suppressed number, including a differently-formatted version of the same
  number
- out-of-hours in `Asia/Dubai`, `Europe/London` and `America/Los_Angeles`,
  asserting that the *same UTC instant* is allowed in one and blocked in another
- **boundary times**: exactly `start`, one second before `start`, exactly `end`,
  one second before `end` — asserting the half-open `[start, end)` rule
- a DST transition day in `Europe/London` and `America/Los_Angeles`
- a non-permitted local day (Friday under the `AE` profile)
- timezone/prefix mismatch, asserted under both the `block` and `warn` settings
- attempt limits at the boundary: at the limit, one under, one over, and an
  attempt falling just outside the rolling window
- unverified number
- call already in flight
- **the all-clear case**, asserting `decision: allow` and every check `pass`
- multiple simultaneous failures, asserting all appear in `blocking_reasons` and
  that `primary_reason` is the highest-severity one
- malformed input — bad E.164, unknown timezone, missing region profile —
  asserting `CHECK_NOT_EVALUABLE` and `decision: block`, never an exception
- a property test asserting the engine never returns `allow` when any check
  returns `block`

**The non-claim guard has its own regression test**: `"We work with 400
companies, do you have news?"` must classify as `unclassified`, not `non_claim`.
This is the case that was found by running the rules by hand before any code was
written, and it is the one most likely to be reintroduced by someone tidying the
patterns later.

**The agent's own opening line is tested against its own rules.** The pinned
first turn from `agent/first_turn.md` is run through the disclosure check and
the Tier 1 claim check and must pass both. The sentence the agent actually says
should not be able to drift out of compliance with the allowlist without the
build going red.

**Post-call checks**, run against the scenario library:

| Scenario | Expects |
|---|---|
| `compliant_meeting_booked` | no violations; `interest: interested`, `meeting_requested: true` |
| `compliant_not_interested` | no violations; `interest: not_interested` |
| `missing_disclosure` | `DISCLOSURE_MISSING` |
| `invented_pricing_claim` | `UNPERMITTED_CLAIM`, `rule_id: PRICE` |
| `out_of_scope_agreement` | `OUT_OF_SCOPE_COMMITMENT` |
| `prospect_opts_out` | `opt_out_requested: true` and a `suppression_entry` written |

Each asserts the expected violations **and** that no others fired. Plus a
golden-file assertion on the set of `unclassified` sentences across all
scenarios, so a pattern change that widens the deterministic blind spot fails
the build rather than passing silently.

**API and webhook.** Contract tests: `409` carries a full decision; `202`
carries an attempt id; a blocked call writes an attempt row and **never calls
the provider** (asserted with a provider double that fails the test if invoked);
an invalid webhook signature writes nothing; a replayed webhook produces one
outcome.

CI (GitHub Actions) runs lint plus this suite only. No secrets are available to
CI and none are required.

### 9.2 Simulated end-to-end

The same scenario library, driven through the real HTTP API and the real UI
rather than through the test harness: pick a prospect, click, and watch the
policy gate, the attempt record, the checks and the outcome write-back happen.

**No real call was placed in the making of this project, and no transcript here
came from a real conversation.** That was a safety decision, not a shortcut —
§2.1 gives the reasoning. What it means for the evidence:

| Proven by the simulated suite | Not proven |
|---|---|
| The policy engine blocks and allows correctly, including at boundaries | That a real ElevenLabs agent obeys the pinned first turn |
| A blocked call never reaches a provider | That the ElevenLabs/Twilio integration works against a live network |
| The post-call checks catch missing disclosure, invented claims, out-of-scope commitments and opt-outs | That the checks catch what a *real* agent invents, as opposed to what I scripted it to invent |
| Outcome extraction and write-back | Audio, latency, interruption, accent and line-quality behaviour |

The right-hand column is the honest cost of the decision. The scripted failures
in the left-hand column were written by me, which means they test the checker
against my imagination rather than against reality.

### 9.3 Keyed evals — manual, never in CI

The Tier 2 LLM adjudicator (§5.2) needs an API key and is therefore run by hand,
never in CI. It is evaluated against a labelled set of sentences — some drawn
from the scenarios, some written to be genuinely ambiguous — and its agreement
rate with my own labels is reported **as a fraction with the denominator
visible**, not as a percentage on its own.

**Rules I am holding to.** No transcript is written by hand and presented as a
real call. No metric is reported that was not produced by a run I actually did.
If the adjudicator does badly, the number goes in the README as it came out.

---

## 10. Build order

Ordered so the project is finished at whatever point work stops. Steps 4 and 6
differ from the original brief because of the decision to simulate; the rest is
unchanged.

1. **Policy engine.** Pure functions, no I/O. Tests first. The best-tested code
   in the repo.
2. **Storage and data model.** SQLite. Prospects, consent, suppression,
   attempts, evaluations, outcomes.
3. **Agent configuration.** Prompt, pinned first turn and permitted-claims list
   as version-controlled files.
4. **Provider seam and `SimulatedProvider`**, plus the scenario library and the
   call-trigger endpoint, which calls the policy engine first and refuses on any
   failure. `ElevenLabsProvider` written to the same interface, unwired.
5. **Post-call processing.** Normalise, verify disclosure, run the Tier 1 claim
   check, extract the structured outcome, write it back.
6. **Eval suites**, separated: the deterministic scenario suite (§9.1, CI, no
   keys) and the keyed Tier 2 eval (§9.3, manual).
7. **GitHub Actions CI.** Lint plus deterministic tests only.
8. **UI, last.** One page (§8). If it starts eating time, it stops.

---

## 11. Decision log

Every decision here was made by the human directing the project. The questions
were put by the AI implementing it; the answers, and the responsibility for
them, are the human's. This section exists because a spec that only states
conclusions hides the part that was actually judgement.

### Taken before the spec was drafted

1. **Claim checking is layered, not purely deterministic or purely LLM.**
   Tier 1 runs in CI with no keys; Tier 2 adjudicates only what Tier 1 could not
   classify. *Why:* a deterministic-only checker misses paraphrase, and an
   LLM-only checker puts a hallucinating component in the compliance path and
   makes CI need keys.

2. **Telephony via a provider seam rather than a bespoke media path.**
   *Why:* the media path is plumbing; the policy layer is the project. This
   later made the simulation pivot cheap — see #14.

3. **Calling hours from an explicit IANA timezone plus per-region windows**,
   with the E.164 prefix cross-checked. *Why:* deriving the timezone from the
   number alone is wrong for ported and roaming mobiles, and hides a real
   failure mode the project should be surfacing.

4. **Consent is a record, not a boolean** — lawful basis, timestamps, evidence,
   withdrawal. *Why:* missing, expired and withdrawn are operationally different
   and a boolean cannot express the difference. It is also the first thing a
   compliance reviewer looks at.

### Taken on review of the draft spec

5. **`AE` is the default region and the seed data is UAE**; `UK` and `US` stay
   in config, exercised by tests. *Why:* it matches the market the demo is
   written for, without a prospect list that pretends to be a global operation.

6. **Attempt limits: 1 per 24h, 3 per rolling 7 days.** *Why:* conservative,
   easy to defend, and tight enough that the block actually fires during a demo.
   A limit nobody sees working is not evidence.

7. **Consent expires 180 days after capture**, with one seed prospect already
   expired. *Why:* it puts `CONSENT_EXPIRED` in front of a reviewer on first
   run instead of burying it in the test suite.

8. **The agent must not speak to voicemail** — say nothing, end the call.
   *Why:* an AI voice leaving an unsupervised message is the single riskiest
   thing this system could do, and machine detection is unreliable enough that
   silence is the correct default. The verification gap this creates is named in
   §7 rather than covered with a weak detector.

9. **Transcripts are kept indefinitely.** *Why:* every transcript in this build
   is scripted, so there is no third-party data to age out. A retention policy
   is named as a real-deployment gap instead of half-built.

10. **The opening line**, pinned:
    *"Hi, I'm an AI assistant calling on behalf of Meridian Communications. I'll
    keep this under a minute. Is now an okay time?"* — discloses the AI first,
    names the principal, and offers an exit in turn one.
    *Implementation note:* the line was chosen with an em-dash before "is now an
    okay time"; it is punctuated as three sentences here so the segmenter treats
    the commitment as its own sentence and checks it against the allowlist,
    rather than letting it ride inside a question and escape review. The wording
    is unchanged.

11. **The consultancy is "Meridian Communications", fictional.** *Why:* reads
    like a real mid-size firm without colliding with one, so no reviewer has to
    wonder whether a real client is involved.

12. **A timezone/prefix mismatch blocks**, configurable to `warn`, both paths
    tested. *Why:* it is a data error that silently defeats the calling-hours
    check, and the fix is a one-field edit.

13. **The UI gets a dry-run "check policy" button.** *Why:* the endpoint already
    exists for the tests, and it is the clearest way to show the policy layer to
    someone who will not read the test suite.

### Taken after the draft, changing the shape of the project

14. **No real calls. Calls are simulated from scripted scenarios.**
    *Why:* it takes the regulatory surface of running the demo to zero, and it
    moves the post-call checks into CI, where they run on every commit instead
    of only when someone picks up a phone. *Cost, stated plainly in §9.2:* the
    provider integration is never exercised, and every failure the checker
    catches is one I wrote.

15. **The dial path is still built, behind the `CallProvider` seam.**
    `SimulatedProvider` is wired; `ElevenLabsProvider` is written to the same
    interface and never instantiated. *Why:* the seam is the part that shows the
    boundary was designed rather than avoided, and it costs very little.

16. **§9.2 became "Simulated end-to-end" rather than a live-call section marked
    NOT RUN.** *Why:* a section describing something that did not happen is
    worse than a section describing what did, next to an explicit list of what
    that does not prove.

**Superseded.** An earlier decision called for three to five live calls to a
verified number, including one with the disclosure deliberately stripped to
prove the post-call check catches a real miss. Decision #14 supersedes it. The
deliberately-broken run survives as the `missing_disclosure` scenario — as a
script rather than a phone call, which is a weaker form of the same evidence.
This is recorded rather than quietly rewritten, because a decision log that only
contains decisions that survived is not a log.
