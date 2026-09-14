"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CallWalkthrough } from "./components/CallWalkthrough";
import { ClaimSandbox } from "./components/ClaimSandbox";
import { ProspectTable } from "./components/ProspectTable";
import { VoiceAgent } from "./components/VoiceAgent";
import {
  API,
  REPO,
  getJSON,
  postJSON,
  type Decision,
  type Health,
  type Prospect,
  type ScenarioSummary,
  type VoiceStatus,
} from "./lib/api";

// The five post-call checks, as the policy engine defines them (SPEC 4.5).
const POST_CALL_CHECKS = 5;

export default function Page() {
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [live, setLive] = useState<Record<string, Decision>>({});
  const [health, setHealth] = useState<Health | null>(null);
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState("psp_0001");
  const walkthrough = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const { prospects: rows } = await getJSON<{ prospects: Prospect[] }>("/prospects");
      setProspects(rows);
      setError(null);

      const decisions = await Promise.all(
        rows.map(async (p) => [p.id, (await postJSON<Decision>(`/prospects/${p.id}/policy-check`, {})).body] as const),
      );
      setLive(Object.fromEntries(decisions));
    } catch {
      setError(
        `The API at ${API} is not responding. It is self-hosted, so it may be restarting — try again in a minute.`,
      );
    }
  }, []);

  useEffect(() => {
    load();
    getJSON<{ scenarios: ScenarioSummary[] }>("/scenarios")
      .then((body) => setScenarios(body.scenarios))
      .catch(() => undefined);
    getJSON<Health>("/healthz")
      .then(setHealth)
      .catch(() => undefined);
    getJSON<VoiceStatus>("/voice/status")
      .then(setVoice)
      .catch(() => setVoice({ enabled: false, max_duration_seconds: 0, reason: "unreachable" }));
  }, [load]);

  function walkThrough(id: string) {
    setSelected(id);
    walkthrough.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const firstDecision = Object.values(live)[0];
  const callable = Object.values(live).filter((d) => d.decision === "allow").length;

  return (
    <>
      <header className="topbar">
        <div className="wrap">
          <div className="brand">
            <strong>Warmline</strong>
            <span>Policy layer for AI outbound calling</span>
          </div>
          <nav className="toplinks">
            <a href={`${REPO}/blob/main/docs/SPEC.md`}>Specification</a>
            <a href={`${REPO}/blob/main/README.md`}>README</a>
            <a href={REPO}>Source</a>
          </nav>
        </div>
      </header>

      <main className="wrap">
        <section className="hero">
          <div className="eyebrow">Technical demo · outbound AI for a PR consultancy</div>
          <h1>Every call passes a gate. Every word is checked afterwards.</h1>
          <p className="lead">
            An AI agent that says the wrong thing to a real person is a regulatory problem, not a bug report.
            Warmline is the layer that decides whether a call may be placed at all, then verifies what the agent
            said — disclosure, approved claims, commitments, opt-outs, market-sensitive news — and writes the result back as data.
          </p>
          <div className="notice">
            <span>
              <b>Nothing here dials a phone.</b> The first section is a real conversation you start in your
              own browser. Everything else is scripted, and every prospect is fictional. The policy checks, the
              claim checker and the database are the real code throughout.
            </span>
          </div>

          <div className="facts">
            <div className="fact">
              <div className="n">{firstDecision ? firstDecision.checks.length : "—"}</div>
              <div className="l">checks before a call is placed</div>
            </div>
            <div className="fact">
              <div className="n">{POST_CALL_CHECKS}</div>
              <div className="l">checks on every transcript</div>
            </div>
            <div className="fact">
              <div className="n">{prospects.length ? `${callable} of ${prospects.length}` : "—"}</div>
              <div className="l">prospects callable right now</div>
            </div>
            <div className="fact">
              <div className="n">{health ? (health.places_real_calls ? "Live" : "None") : "—"}</div>
              <div className="l">real calls placed</div>
            </div>
          </div>

          {error && <div className="error-bar">{error}</div>}
        </section>

        <section className="block">
          <div className="section-head">
            <span className="num">01</span>
            <div>
              <h2>Talk to the agent</h2>
              <p>
                A real voice agent, not a script. You play the prospect. When the conversation ends, the transcript
                ElevenLabs stored is run through the same post-call checks as every other call on this page — so
                if you can talk it into inventing a price or ignoring an opt-out, you will see it caught.
              </p>
            </div>
          </div>
          <VoiceAgent status={voice} />
        </section>

        <section className="block">
          <div className="section-head">
            <span className="num">02</span>
            <div>
              <h2>Walk a call through the policy layer</h2>
              <p>
                Three questions, in order: should we call this person, did the agent say anything it should not
                have, and what happened. A call that fails the first never reaches the second.
              </p>
            </div>
          </div>
          {prospects.length > 0 && scenarios.length > 0 && (
            <CallWalkthrough
              ref={walkthrough}
              prospects={prospects}
              scenarios={scenarios}
              selected={selected}
              onSelect={setSelected}
              onSaved={load}
            />
          )}
        </section>

        <section className="block">
          <div className="section-head">
            <span className="num">03</span>
            <div>
              <h2>Try to get a claim past the checker</h2>
              <p>
                Type anything as though the agent had said it. This is the deterministic tier that runs on every
                transcript — no model, same code as production. It will not catch everything, and it says so:
                a sentence it cannot place is reported as unclassified rather than waved through.
              </p>
            </div>
          </div>
          <ClaimSandbox />
        </section>

        <section className="block">
          <div className="section-head">
            <span className="num">04</span>
            <div>
              <h2>Prospects</h2>
              <p>
                Whether each record is callable at this moment, and the last call on it. Five of the six are
                seeded to fail a different check, so the policy layer is visible without reading the tests.
              </p>
            </div>
          </div>
          <ProspectTable prospects={prospects} live={live} selected={selected} onWalkThrough={walkThrough} />
        </section>
      </main>

      <footer>
        <div className="wrap">
          <p>
            Built as a technical assessment. The implementation was AI-directed: the specification, its decision
            log and the commit history show what was decided, what was corrected, and how it was verified.
            {health && (
              <>
                {" "}
                Policy <span className="mono">{health.policy_version}</span> ·{" "}
                <span className="mono">{health.config_digest.slice(0, 19)}…</span>
              </>
            )}
          </p>
          <nav>
            <a href={`${REPO}/blob/main/docs/SPEC.md`}>Specification</a>
            <a href={`${REPO}/blob/main/README.md`}>README</a>
            <a href={REPO}>Source</a>
          </nav>
        </div>
      </footer>
    </>
  );
}
