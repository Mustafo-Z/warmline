# Warmline

A small demo of the safety layer around an AI voice agent that calls prospects
for a PR consultancy. Before a call, it checks whether the call is allowed.
After a call, it checks the transcript for anything the agent shouldn't have
said.

Nothing here dials a phone. Outbound calls are simulated with scripted
conversations that go through the same code a real call would. The only real
conversations are the ones you start yourself on the page, in your browser.

## For reviewers

- **Live demo:** https://warmline.mziyo.com. The first section is the live voice
  agent; the passcode comes with the link. The API runs on a Mac mini at home,
  so it can occasionally be down.
- **Spec:** [docs/SPEC.md](docs/SPEC.md) was the first commit. Section 11 is the
  decision log: each question I was asked, what I chose and why.
- **Tests first:** [`739d371`](https://github.com/Mustafo-Z/warmline/commit/739d371)
  adds the policy engine tests with 59 of 66 failing, and
  [`29704cc`](https://github.com/Mustafo-Z/warmline/commit/29704cc) makes them
  pass.
- **Mistakes caught:** see [How it was built](#how-it-was-built) and
  [What the live conversations found](#what-the-live-conversations-found).
- **Time:** about two hours of my own time, between 9 and 14 September. Claude
  wrote the code and drafted the docs and commit messages. I made the decisions,
  tested the running system and talked to the agent.

## What it checks

Before a call, nine checks run and the call is blocked unless all of them pass:
the number is on a verified list, consent exists and hasn't expired or been
withdrawn, the number isn't suppressed, the timezone matches the number's
country, it's inside local calling hours, the attempt limits aren't used up, and
no other call to that prospect is running. Every block comes with a reason and,
where possible, the time it would pass. The engine is a pure function with no
database, clock or file access, so the edge cases can be tested exactly.

During a call, the agent's first line is fixed in
[agent/first_turn.md](agent/first_turn.md) and says it's an AI. That's only an
instruction to a language model, so it gets checked afterwards.

After a call, five checks run on the transcript: the AI disclosure, claims that
aren't on the approved list, commitments the agent isn't allowed to make, an
opt-out the agent ignored, and the agent encouraging coverage of
market-sensitive news such as an upcoming stock listing. Each violation quotes
the sentence and names the rule.

What the agent may say is in [policy/permitted_claims.yaml](policy/permitted_claims.yaml),
and the calling rules are in [policy/calling_windows.yaml](policy/calling_windows.yaml),
so a change to either shows up as a diff.

## How it was built

I directed Claude Code and checked what came back. The spec was written and
agreed first, with every open question put to me, and the policy engine tests
were committed failing before the engine existed. There are 274 tests, and CI
runs them on every push without any API keys.

Things that were wrong and got caught:

- The claim checker rejected the agent's own opening line. Its rule was "no
  proper nouns", when it should have been "no proper nouns that aren't in the
  approved claim", and the approved claim contains "AI".
- The commitment check ran before the approved-claims check, so it flagged
  "I'll send a calendar invite" as promising to send a document.
- The UAE calling rules used the pre-2022 working week, so every prospect was
  blocked on a Friday. Calling hours are now set per day, with a Friday half day.
- One SQLite connection shared across FastAPI's threads returned broken rows
  when requests overlapped. It now sits behind a lock, and the regression test
  was checked to fail without it.
- The prospect table hid a completed call as soon as a later attempt was
  blocked.
- After the first live call, the page showed a green tick while 11 of the
  agent's 19 sentences hadn't been matched to the approved list at all. They now
  show as unverified.

## What the live conversations found

The transcripts are in [evals/live/](evals/live/), exactly as ElevenLabs stored
them, and the test suite runs the same checks on them. I played the prospect
each time.

1. **First call.** I said my company was going public in two weeks, and the
   agent said that was worth pitching. Nothing checked for that, and for a
   listed company it's the wrong thing to say. I added the `SENSITIVE_NEWS`
   check and a prompt rule to hand that kind of news to a consultant. The same
   call showed the agent couldn't hang up, because agents created through the
   ElevenLabs API don't get the end-call tool by default. It also showed the
   outcome extractor missing both the agreed meeting and the news. All of it is
   fixed, with this transcript as the regression test.
2. **Accidental call.** It ended at "Hi," and was scored as a missing
   disclosure. A call that ends during the opening line with no reply is now
   recorded but not scored.
3. **Second call.** I said the same thing. This time the agent passed it to a
   consultant, the check stayed quiet, the extractor got the meeting and the
   news right, and the agent hung up by itself. After this call I swapped the
   voice for a less synthetic one.
4. **Two calls about pricing.** The agent explained pay-on-results without
   promising coverage, and no check fired. Its wording didn't match the
   approved claim closely enough, though, so those sentences show as
   unverified. The extractor also read "No, thanks. I'm good." as unclear
   instead of a no.
5. **Slow replies.** The second pricing call felt slow, so I measured it with
   `python -m warmline.voice.timing` before changing anything. The agent took a
   median of 2.5 seconds to start talking, and 3.45 seconds at worst. Of that
   worst gap, 3.03 seconds was the language model and 0.17 was the voice. The
   longest answers were the slowest, and they pushed the call to 95 seconds,
   when the opening line promises under a minute. I switched the model from
   Claude Sonnet 4.5 to Haiku 4.5 and limited replies to two short sentences.
6. **After the change.** The timing script confirms, from ElevenLabs' billing
   record, that the next conversation ran on Haiku. The agent took a median of
   1.2 seconds to start talking, and 1.57 at worst. The model's slowest first
   sentence went from 3.03 seconds to 0.70, the longest reply from 52 words to
   27, and the call took 48 seconds. That's one short conversation against one
   long one, so it's a rough comparison. In the slowest reply, waiting to be
   sure I'd finished talking now took as long as the model.

## What isn't proven

- No real phone call has been placed. The ElevenLabs phone provider is written
  but not wired up, so it has never run against a real network.
- The scripted failures only cover failures someone thought of. The live calls
  help, but five conversations with one person isn't much evidence.
- The voicemail rule, to say nothing to an answering machine, is only in the
  prompt. Nothing checks it.
- The deterministic claim checker can't catch an invented claim that's
  paraphrased well enough to avoid every pattern. It does report what it
  couldn't classify, and a test fails if that list grows.
- The LLM claim checker in [evals/](evals/) needs an API key and has never been
  run, so there are no results for it.

## What I would do next

- Recognise pleasantries like "Have a great day!", which make up most of the
  unverified sentences.
- Replace the keyword outcome extractor with an LLM. It's the weakest part.
- Place real calls to a number I own, and keep every transcript, including the
  bad ones.
- Add a scheduler that acts on the retry time. Calls are started by hand for
  now.
- Screen against real do-not-call registers, not just the suppression list.
- Check what the agent says during the call, not only afterwards.
- Tune how long the agent waits to decide the prospect has finished. On the
  Haiku call that wait was as long as the model's part of the slowest reply.
- Move to a real database with a connection per request.
- Add a retention policy for transcripts.

## Running it locally

Python 3.11+ and Node 20+.

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn warmline.api.main:app --port 8000
```

```bash
cd web && npm install && npm run dev
```

```bash
.venv/bin/python -m pytest
```

The seed prospects are in Dubai, where calling hours are 09:00 to 18:00 Monday
to Thursday and 09:00 to 12:00 on Friday. Outside those hours every row shows
"Outside permitted calling hours", because simulated calls go through the same
gate. Each number also gets one call per 24 hours, so a second simulated call to
the same prospect is refused.

The live voice agent needs an ElevenLabs key. Setting it up, and how the hosted
version runs, is in [deploy/README.md](deploy/README.md).

## Repository map

```
docs/SPEC.md            spec and decision log
policy/*.yaml           calling windows, verified numbers, approved claims, disclosure rule
agent/                  system prompt, fixed opening line, agent config
scenarios/*.json        scripted conversations, used by the tests and the page
src/warmline/policy     pre-dial engine
src/warmline/postcall   transcript checks and outcome extraction
src/warmline/providers  call provider interface; only the simulated one is wired up
src/warmline/api        FastAPI
src/warmline/voice      live browser sessions: ElevenLabs client, agent sync, timing
tests/                  deterministic tests, no keys needed
evals/                  LLM claim checker eval, run by hand
evals/live/             real conversations with the agent
deploy/                 Mac mini deployment
web/                    Next.js page
```

## Regulatory note

I'm not a lawyer. These are the rules the design was based on. In the US, the
FCC treats AI-generated voices in unsolicited calls as artificial voices under
the TCPA. The UAE restricts marketing calls to permitted hours and days and
requires registration. In the UK, PECR requires TPS and CTPS screening.

This project models consent, suppression, calling hours, attempt limits and
disclosure. It doesn't screen do-not-call registers, handle registration or
replace legal review, and it shouldn't be pointed at a real prospect list.
