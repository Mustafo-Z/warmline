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
type Violation = { code: string; rule_id: string | null; quote: string };
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
