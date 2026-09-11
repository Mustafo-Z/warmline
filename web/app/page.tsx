"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// Plain language for the codes the policy engine emits. The engine's own
// `message` is shown underneath; this is the headline a non-engineer reads.
const REASONS: Record<string, string> = {
  NUMBER_NOT_VERIFIED: "Number is not on the verified allowlist",
  CONSENT_MISSING: "No consent record",
  CONSENT_EXPIRED: "Consent has expired",
  CONSENT_WITHDRAWN: "Consent was withdrawn",
  NUMBER_SUPPRESSED: "Number is suppressed",
  TIMEZONE_PREFIX_MISMATCH: "Timezone does not match the number's country",
  OUTSIDE_CALLING_HOURS: "Outside permitted calling hours",
  ATTEMPT_LIMIT_REACHED: "Attempt limit reached",
  CALL_IN_FLIGHT: "A call is already in progress",
  CHECK_NOT_EVALUABLE: "A check could not be evaluated",
};

type Check = { code: string; result: string; message?: string };
type Decision = {
  decision: "allow" | "block";
  primary_reason: string | null;
  blocking_reasons: string[];
  checks: Check[];
};
type Violation = { code: string; rule_id: string | null; quote: string; turn_index: number };
type Outcome = {
  interest: string;
  disclosure_ok: boolean;
  meeting_requested: boolean;
  opt_out_requested: boolean;
  violations: Violation[];
  transcript_source: string;
  news_summary: string | null;
};
type Prospect = {
  id: string;
  full_name: string;
  company: string;
  phone_e164: string;
  timezone: string;
  is_fixture: boolean;
  last_attempt: { status: string; scenario: string | null } | null;
  last_policy_decision: Decision | null;
  last_outcome: Outcome | null;
};
type Scenario = { id: string; label: string };
type Turn = { index: number; role: string; text: string };
type Classification = {
  turn_index: number;
  sentence: string;
  verdict: string;
  rule_id: string | null;
  explanation: string;
};
type ScenarioDetail = {
  label: string;
  description: string;
  transcript: { turns: Turn[] };
  checks: {
    disclosure_ok: boolean;
    violations: Violation[];
    classifications: Classification[];
  };
  outcome: {
    interest: string;
    news_summary: string | null;
    meeting_requested: boolean;
    meeting_preferences: string | null;
    opt_out_requested: boolean;
  };
};
type SandboxResult = {
  sentences: { sentence: string; verdict: string; rule_id: string | null; explanation: string }[];
};

const VERDICT_TONE: Record<string, string> = {
  prohibited: "bad",
  commitment: "bad",
  unclassified: "neutral",
  permitted: "ok",
  non_claim: "neutral",
};

const VERDICT_LABEL: Record<string, string> = {
  prohibited: "NOT ALLOWED",
  commitment: "OUT OF SCOPE",
  unclassified: "UNCLASSIFIED",
  permitted: "PERMITTED",
  non_claim: "NOT A CLAIM",
};

const SANDBOX_EXAMPLES = [
  "We work with companies on press coverage.",
  "Our retainers start at 5000 dollars a month.",
  "We can get you into Forbes within 30 days.",
  "We work with 400 companies, do you have news?",
  "Our consultants are all former journalists.",
];

function CallPanel({ scenarios }: { scenarios: Scenario[] }) {
  const [chosen, setChosen] = useState("");
  const [detail, setDetail] = useState<ScenarioDetail | null>(null);
  const [shown, setShown] = useState(0);
  const [running, setRunning] = useState(false);
  const [sandboxText, setSandboxText] = useState("");
  const [sandbox, setSandbox] = useState<SandboxResult | null>(null);

  const scenarioId = chosen || scenarios[0]?.id || "";
  const turns = detail?.transcript.turns ?? [];
  const finished = detail !== null && shown >= turns.length;

  // Sentences the checker flagged, so the offending turn can be marked as the
  // transcript plays rather than only in a list underneath it.
  const flaggedTurns = new Set((detail?.checks.violations ?? []).map((v) => v.turn_index));

  async function start() {
    setRunning(true);
    setDetail(null);
    setShown(0);
    const response = await fetch(`${API}/scenarios/${scenarioId}`);
    const body: ScenarioDetail = await response.json();
    setDetail(body);

    for (let i = 1; i <= body.transcript.turns.length; i++) {
      await new Promise((r) => setTimeout(r, i === 1 ? 250 : 850));
      setShown(i);
    }
    setRunning(false);
  }

  async function checkSentence(text: string) {
    setSandboxText(text);
    if (!text.trim()) {
      setSandbox(null);
      return;
    }
    const response = await fetch(`${API}/claims/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    setSandbox(await response.json());
  }

  return (
    <div className="panel">
      <h2>What a call looks like</h2>
      <p className="hint">
        Pick a conversation and play it. The agent&apos;s opening is fixed and discloses the AI;
        everything after it is scripted. When the call ends, the same checks that run in
        production run here, over the transcript you just watched.
      </p>

      <div className="controls">
        <select value={scenarioId} onChange={(e) => setChosen(e.target.value)} disabled={running}>
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <button onClick={start} disabled={running || !scenarioId}>
          {running ? "Call in progress…" : "Start call"}
        </button>
      </div>

      {detail && (
        <div className="transcript">
          {turns.slice(0, shown).map((turn) => (
            <div
              key={turn.index}
              className={`turn ${turn.role} ${flaggedTurns.has(turn.index) && finished ? "flagged" : ""}`}
            >
              <span className="who">{turn.role}</span>
              <span className="said">{turn.text}</span>
            </div>
          ))}
          {running && <div className="turn"><span className="who" /><span className="said">…</span></div>}
        </div>
      )}

      {detail && finished && (
        <div className="checks">
          <h3>Post-call checks</h3>

          <div className={`verdict ${detail.checks.disclosure_ok ? "ok" : "bad"}`}>
            <span className="label">{detail.checks.disclosure_ok ? "DISCLOSED" : "NO DISCLOSURE"}</span>
            <span className="body">
              {detail.checks.disclosure_ok
                ? "The agent said it was an AI in its first turn."
                : "The agent never disclosed that it was an AI."}
            </span>
          </div>

          {detail.checks.violations.length === 0 ? (
            <div className="verdict ok">
              <span className="label">NO VIOLATIONS</span>
              <span className="body">Every sentence the agent said is inside the allowlist.</span>
            </div>
          ) : (
            detail.checks.violations.map((v, i) => (
              <div key={i} className="verdict bad">
                <span className="label">{v.rule_id ?? v.code}</span>
                <span className="body">
                  “{v.quote}”
                  <span className="why">
                    {v.code}
                    {" — "}
                    {detail.checks.classifications.find((c) => c.sentence === v.quote)
                      ?.explanation ?? ""}
                  </span>
                </span>
              </div>
            ))
          )}

          <div className="verdict neutral">
            <span className="label">OUTCOME</span>
            <span className="body">
              {detail.outcome.interest.replace("_", " ")}
              {detail.outcome.meeting_requested ? ", meeting requested" : ""}
              {detail.outcome.meeting_preferences ? ` (${detail.outcome.meeting_preferences})` : ""}
              {detail.outcome.opt_out_requested ? ", opted out — number suppressed" : ""}
              {detail.outcome.news_summary && (
                <span className="why">{detail.outcome.news_summary}</span>
              )}
            </span>
          </div>
        </div>
      )}

      <div className="sandbox">
        <h2>Try to get something past the checker</h2>
        <p className="hint">
          Type anything as though the agent had said it. This runs the same Tier 1 code the
          post-call check uses — deterministic, no model involved — and reports what it makes of
          each sentence.
        </p>
        <div className="examples">
          {SANDBOX_EXAMPLES.map((example) => (
            <button key={example} onClick={() => checkSentence(example)}>
              {example}
            </button>
          ))}
        </div>
        <textarea
          value={sandboxText}
          placeholder="We can get you on the front page by next week."
          onChange={(e) => checkSentence(e.target.value)}
        />
        {sandbox && sandbox.sentences.length > 0 && (
          <div className="checks">
            {sandbox.sentences.map((s, i) => (
              <div key={i} className={`verdict ${VERDICT_TONE[s.verdict] ?? "neutral"}`}>
                <span className="label">{VERDICT_LABEL[s.verdict] ?? s.verdict}</span>
                <span className="body">
                  “{s.sentence}”
                  <span className="why">
                    {s.rule_id ? `${s.rule_id} — ` : ""}
                    {s.explanation}
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PolicyCell({ decision }: { decision: Decision | null }) {
  if (!decision) return <span style={{ color: "#6b6b66" }}>not checked</span>;
  if (decision.decision === "allow") return <span className="tag allow">ALLOWED</span>;

  const reason = decision.primary_reason ?? "";
  const detail = decision.checks.find((c) => c.code === reason)?.message;
  return (
    <>
      <span className="tag block">BLOCKED</span>
      <span className="reason">
        {REASONS[reason] ?? reason}
        {decision.blocking_reasons.length > 1
          ? ` (+${decision.blocking_reasons.length - 1} more)`
          : ""}
      </span>
      {detail && <span className="reason">{detail}</span>}
    </>
  );
}

function OutcomeCell({ outcome }: { outcome: Outcome | null }) {
  if (!outcome) return <span style={{ color: "#6b6b66" }}>—</span>;
  return (
    <>
      <div>
        {outcome.interest.replace("_", " ")}
        {outcome.meeting_requested ? ", meeting requested" : ""}
        {outcome.opt_out_requested ? ", opted out" : ""}
      </div>
      {!outcome.disclosure_ok && <div className="violation">disclosure check failed</div>}
      {outcome.violations.map((v, i) => (
        <div key={i} className="violation">
          {v.code}
          {v.rule_id ? ` (${v.rule_id})` : ""}
          <span className="reason">“{v.quote}”</span>
        </div>
      ))}
      {outcome.news_summary && <span className="reason">{outcome.news_summary}</span>}
    </>
  );
}

export default function Page() {
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, Decision>>({});
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${API}/prospects`);
      setProspects((await response.json()).prospects);
      setError(null);
    } catch {
      setError(`Cannot reach the API at ${API}. Is uvicorn running?`);
    }
  }, []);

  useEffect(() => {
    refresh();
    fetch(`${API}/scenarios`)
      .then((r) => r.json())
      .then((body) => setScenarios(body.scenarios))
      .catch(() => undefined);
  }, [refresh]);

  async function checkPolicy(id: string) {
    setBusy(id);
    const response = await fetch(`${API}/prospects/${id}/policy-check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const decision = await response.json();
    setChecked((prior) => ({ ...prior, [id]: decision }));
    setBusy(null);
  }

  async function simulate(id: string) {
    setBusy(id);
    await fetch(`${API}/prospects/${id}/calls`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario: chosen[id] ?? scenarios[0]?.id }),
    });
    await refresh();
    setBusy(null);
  }

  return (
    <main>
      <h1>Warmline</h1>
      <p className="sub">
        Outbound AI voice agent for a PR consultancy. This page is the policy layer: whether a
        call may be placed, and what the agent said if it was.
      </p>

      <div className="banner">
        <strong>Nothing here dials.</strong> Every prospect is fictional and every call is
        replayed from a scripted scenario. No telephone call was placed in the making of this
        project.
      </div>

      {error && <div className="banner">{error}</div>}

      {scenarios.length > 0 && <CallPanel scenarios={scenarios} />}

      <table>
        <thead>
          <tr>
            <th>Prospect</th>
            <th>Number</th>
            <th>Policy</th>
            <th>Last outcome</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {prospects.map((prospect) => (
            <tr key={prospect.id}>
              <td className="name">
                {prospect.full_name}
                <span className="company">{prospect.company}</span>
                {prospect.is_fixture && <span className="tag sim">FICTIONAL</span>}
              </td>
              <td>
                <code>{prospect.phone_e164}</code>
                <span className="company">{prospect.timezone}</span>
              </td>
              <td>
                <PolicyCell decision={checked[prospect.id] ?? prospect.last_policy_decision} />
              </td>
              <td>
                <OutcomeCell outcome={prospect.last_outcome} />
                {prospect.last_attempt?.scenario && (
                  <span className="reason">
                    <span className="tag sim">SIMULATED</span> {prospect.last_attempt.scenario}
                  </span>
                )}
              </td>
              <td>
                <div className="actions">
                  <button
                    onClick={() => checkPolicy(prospect.id)}
                    disabled={busy === prospect.id}
                  >
                    Check policy
                  </button>
                  <select
                    value={chosen[prospect.id] ?? scenarios[0]?.id ?? ""}
                    onChange={(e) =>
                      setChosen((prior) => ({ ...prior, [prospect.id]: e.target.value }))
                    }
                  >
                    {scenarios.map((scenario) => (
                      <option key={scenario.id} value={scenario.id}>
                        {scenario.label}
                      </option>
                    ))}
                  </select>
                  <button onClick={() => simulate(prospect.id)} disabled={busy === prospect.id}>
                    Simulate call
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="sub" style={{ marginTop: "1.5rem" }}>
        <strong>Check policy</strong> evaluates the pre-dial rules and shows the decision without
        doing anything. <strong>Simulate call</strong> runs the same gate, then replays the chosen
        scenario through the disclosure and claim checks and writes the outcome back.
      </p>
    </main>
  );
}
