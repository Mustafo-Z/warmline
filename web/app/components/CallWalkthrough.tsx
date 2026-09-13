"use client";

import { forwardRef, useEffect, useState, type ReactNode } from "react";
import {
  CHECK_LABELS,
  REASON_SHORT,
  VERDICT_LABEL,
  VERDICT_TONE,
  formatInZone,
  getJSON,
  postJSON,
  zoneLabel,
  type Decision,
  type Prospect,
  type ScenarioDetail,
  type ScenarioSummary,
  type Violation,
} from "../lib/api";

type Phase = "idle" | "gate" | "blocked" | "calling" | "done";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Violations about something the agent *said*, which can be pointed at inside
// the transcript. Disclosure violations are about something it did not say.
const QUOTABLE = new Set(["UNPERMITTED_CLAIM", "OUT_OF_SCOPE_COMMITMENT", "OPT_OUT_NOT_HONOURED"]);

function highlight(text: string, flags: Violation[]): ReactNode {
  if (flags.length === 0) return text;
  const parts: ReactNode[] = [];
  let rest = text;
  flags.forEach((flag, i) => {
    const at = rest.indexOf(flag.quote);
    if (at < 0) return;
    parts.push(rest.slice(0, at));
    parts.push(
      <mark key={i} title={`${flag.code}${flag.rule_id ? ` · ${flag.rule_id}` : ""}`}>
        {flag.quote}
      </mark>,
    );
    rest = rest.slice(at + flag.quote.length);
  });
  parts.push(rest);
  return parts;
}

/** The instant every blocking check would pass, if they are all waiting on time. */
function nextPermittedTime(decision: Decision): string | null {
  const blocking = decision.checks.filter((c) => c.result === "block");
  if (blocking.length === 0) return null;
  if (!blocking.every((c) => c.recoverable === "after" && c.retry_after)) return null;
  return blocking.map((c) => c.retry_after as string).sort().at(-1) ?? null;
}

type Props = {
  prospects: Prospect[];
  scenarios: ScenarioSummary[];
  selected: string;
  onSelect: (id: string) => void;
  onSaved: () => void;
};

export const CallWalkthrough = forwardRef<HTMLDivElement, Props>(function CallWalkthrough(
  { prospects, scenarios, selected, onSelect, onSaved },
  ref,
) {
  const [scenarioId, setScenarioId] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [checksShown, setChecksShown] = useState(0);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [detail, setDetail] = useState<ScenarioDetail | null>(null);
  const [turnsShown, setTurnsShown] = useState(0);
  const [saved, setSaved] = useState<string | null>(null);

  const prospect = prospects.find((p) => p.id === selected);
  const scenario = scenarios.find((s) => s.id === (scenarioId || scenarios[0]?.id));
  const busy = phase === "gate" || phase === "calling";

  // Choosing a different prospect or conversation starts from a clean slate.
  useEffect(() => {
    setPhase("idle");
    setDecision(null);
    setDetail(null);
    setAsOf(null);
    setSaved(null);
  }, [selected, scenarioId]);

  async function run(evaluateAt: string | null) {
    if (!prospect || !scenario) return;
    setSaved(null);
    setDetail(null);
    setTurnsShown(0);
    setChecksShown(0);
    setAsOf(evaluateAt);

    // 1. The gate, against the prospect's real record.
    setPhase("gate");
    const { body: gate } = await postJSON<Decision>(
      `/prospects/${prospect.id}/policy-check`,
      evaluateAt ? { as_of: evaluateAt } : {},
    );
    setDecision(gate);
    for (let i = 1; i <= gate.checks.length; i++) {
      await sleep(110);
      setChecksShown(i);
    }
    await sleep(350);

    if (gate.decision === "block") {
      setPhase("blocked");
      return;
    }

    // 2. The call itself: a scripted conversation, played back.
    setPhase("calling");
    const conversation = await getJSON<ScenarioDetail>(`/scenarios/${scenario.id}`);
    setDetail(conversation);
    for (let i = 1; i <= conversation.transcript.turns.length; i++) {
      await sleep(i === 1 ? 300 : 900);
      setTurnsShown(i);
    }
    await sleep(500);

    // 3 and 4 render from the same response once the call has ended.
    setPhase("done");
  }

  async function saveToRecord() {
    if (!prospect || !scenario) return;
    const { status, body } = await postJSON<{
      attempt_id: string;
      policy?: Decision;
    }>(`/prospects/${prospect.id}/calls`, { scenario: scenario.id });

    if (status === 202) {
      setSaved(`Saved as ${body.attempt_id}. The prospect table below now shows this call.`);
    } else if (status === 409 && body.policy) {
      const reason = body.policy.primary_reason ?? "";
      setSaved(
        `Refused, and recorded as a blocked attempt (${body.attempt_id}): ${REASON_SHORT[reason] ?? reason}. ` +
          "Saving runs the gate for real, at the real time.",
      );
    } else {
      setSaved(`The API returned ${status}.`);
    }
    onSaved();
  }

  const turns = detail?.transcript.turns ?? [];
  const violations = detail?.checks.violations ?? [];
  const retryAt = decision ? nextPermittedTime(decision) : null;
  const hours = decision?.checks.find((c) => c.code === "OUTSIDE_CALLING_HOURS");
  const localTime = (hours?.detail?.local_time as string | undefined) ?? decision?.evaluated_at;

  const gateStep = phase === "idle" ? "" : phase === "gate" ? "active" : phase === "blocked" ? "stopped" : "done";
  const callStep = phase === "calling" ? "active" : phase === "done" ? "done" : "";
  const laterStep = phase === "done" ? "done" : "";

  const claimViolations = violations.filter((v) => v.code === "UNPERMITTED_CLAIM");
  const commitmentViolations = violations.filter((v) => v.code === "OUT_OF_SCOPE_COMMITMENT");
  const optOutViolations = violations.filter((v) => v.code === "OPT_OUT_NOT_HONOURED");
  const explanationFor = (quote: string) =>
    detail?.checks.classifications.find((c) => c.sentence === quote)?.explanation ?? "";

  return (
    <div className="card walk" ref={ref}>
      <div className="walk-controls">
        <div className="field">
          <label htmlFor="prospect">Prospect</label>
          <select id="prospect" value={selected} onChange={(e) => onSelect(e.target.value)} disabled={busy}>
            {prospects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.full_name} — {p.company}
              </option>
            ))}
          </select>
          {prospect && (
            <p className="desc">
              <span className="mono">{prospect.phone_e164}</span> · {zoneLabel(prospect.timezone)}
            </p>
          )}
        </div>

        <div className="field">
          <label htmlFor="scenario">Conversation</label>
          <select
            id="scenario"
            value={scenario?.id ?? ""}
            onChange={(e) => setScenarioId(e.target.value)}
            disabled={busy}
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          {scenario && <p className="desc">{scenario.description}</p>}
        </div>

        <button className="btn primary" onClick={() => run(null)} disabled={busy || !prospect || !scenario}>
          {phase === "gate" ? "Checking policy…" : phase === "calling" ? "Call in progress…" : "Place call"}
        </button>

        <p className="desc" style={{ marginTop: 4 }}>
          The gate runs against this prospect&apos;s real record and the real time. The conversation is
          scripted. Nothing is dialled and nothing is saved unless you ask.
        </p>
      </div>

      <div className="walk-body">
        {phase === "idle" ? (
          <div className="empty">
            <strong>Choose a prospect and a conversation, then place the call.</strong>
            <span>Try Priya Raman to see a call that never happens.</span>
          </div>
        ) : (
          <div className="steps">
            {/* 1. Pre-dial gate */}
            <div className={`step ${gateStep}`}>
              <div className="dot">1</div>
              <div className="step-head">
                <h3>Pre-dial gate</h3>
                {localTime && prospect && (
                  <span className="meta">
                    {asOf ? "Evaluated as of " : "Evaluated at "}
                    {formatInZone(localTime, prospect.timezone)} in {zoneLabel(prospect.timezone)}
                  </span>
                )}
              </div>
              <p className="step-question">Should we call this person right now?</p>

              {decision && (
                <ul className="checklist">
                  {decision.checks.slice(0, checksShown).map((check, i) => {
                    const tone = check.result === "pass" ? "ok" : check.result === "warn" ? "warn" : "bad";
                    return (
                      <li key={`${check.code}-${i}`}>
                        <span className={`icon ${tone}`}>{check.result === "pass" ? "✓" : "✕"}</span>
                        <span>
                          {CHECK_LABELS[check.code] ?? check.code}
                          {check.result !== "pass" && check.message && <span className="msg">{check.message}</span>}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}

              {phase === "blocked" && decision && (
                <div className="callout bad">
                  <strong>Blocked. The agent never dials.</strong>
                  {decision.blocking_reasons.length} of {decision.checks.length} checks failed. The reason a
                  human sees first is{" "}
                  <b>{REASON_SHORT[decision.primary_reason ?? ""] ?? decision.primary_reason}</b> — permanent
                  blocks outrank ones that will clear on their own.
                  {retryAt && prospect ? (
                    <div>
                      <button className="btn small" onClick={() => run(retryAt)}>
                        See it at the next permitted time · {formatInZone(retryAt, prospect.timezone)}
                      </button>
                    </div>
                  ) : (
                    <div style={{ marginTop: 6 }}>
                      Waiting will not fix this one. It needs someone to change the record.
                    </div>
                  )}
                </div>
              )}

              {(phase === "calling" || phase === "done") && decision && (
                <div className="callout ok">
                  <strong>All {decision.checks.length} checks passed.</strong>
                  {asOf
                    ? "Evaluated at a future instant using the policy-check endpoint's as_of parameter; the record itself was not changed."
                    : "The call is allowed to proceed."}
                </div>
              )}
            </div>

            {/* 2. The call */}
            {(phase === "calling" || phase === "done") && (
              <div className={`step ${callStep}`}>
                <div className="dot">2</div>
                <div className="step-head">
                  <h3>The call</h3>
                  <span className="meta">Scripted · {scenario?.label}</span>
                </div>
                <p className="step-question">What did the agent actually say?</p>
                <div className="chat">
                  {turns.slice(0, turnsShown).map((turn) => {
                    const flags =
                      phase === "done"
                        ? violations.filter((v) => v.turn_index === turn.index && QUOTABLE.has(v.code))
                        : [];
                    return (
                      <div key={turn.index} className={`bubble-row ${turn.role}`}>
                        <div className="bubble">
                          <span className="who">
                            {turn.role === "agent" ? "AI agent · Meridian Communications" : prospect?.full_name}
                          </span>
                          {highlight(turn.text, flags)}
                        </div>
                      </div>
                    );
                  })}
                  {phase === "calling" && turnsShown < turns.length && (
                    <div className="typing">
                      <span>●</span> <span>●</span> <span>●</span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 3. Post-call checks */}
            {phase === "done" && detail && (
              <div className={`step ${laterStep}`}>
                <div className="dot">3</div>
                <div className="step-head">
                  <h3>Post-call checks</h3>
                  <span className="meta">
                    {violations.length === 0 ? "No violations" : `${violations.length} violation${violations.length > 1 ? "s" : ""}`}
                  </span>
                </div>
                <p className="step-question">Did it say anything it should not have?</p>

                <div className="results">
                  <div className="result">
                    <span className={`icon ${detail.checks.disclosure_ok ? "ok" : "bad"}`}>
                      {detail.checks.disclosure_ok ? "✓" : "✕"}
                    </span>
                    <div>
                      <div className="title">Disclosed that it is an AI, in its first turn</div>
                      {!detail.checks.disclosure_ok && (
                        <div className="sub">
                          {violations.find((v) => v.code.startsWith("DISCLOSURE"))?.code} — the prospect was never
                          told they were talking to an AI.
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="result">
                    <span className={`icon ${claimViolations.length ? "bad" : "ok"}`}>{claimViolations.length ? "✕" : "✓"}</span>
                    <div>
                      <div className="title">Every claim is on the approved list</div>
                      {claimViolations.map((v, i) => (
                        <div className="quote" key={i}>
                          “{v.quote}”
                          <span className="why">
                            {v.rule_id} · {explanationFor(v.quote)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="result">
                    <span className={`icon ${commitmentViolations.length ? "bad" : "ok"}`}>
                      {commitmentViolations.length ? "✕" : "✓"}
                    </span>
                    <div>
                      <div className="title">Made no commitment it had no authority to make</div>
                      {commitmentViolations.map((v, i) => (
                        <div className="quote" key={i}>
                          “{v.quote}”
                          <span className="why">
                            {v.rule_id} · {explanationFor(v.quote)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="result">
                    <span
                      className={`icon ${
                        !detail.checks.opt_out_requested ? "neutral" : optOutViolations.length ? "bad" : "ok"
                      }`}
                    >
                      {!detail.checks.opt_out_requested ? "–" : optOutViolations.length ? "✕" : "✓"}
                    </span>
                    <div>
                      <div className="title">Honoured an opt-out</div>
                      <div className="sub">
                        {!detail.checks.opt_out_requested
                          ? "The prospect did not ask to stop."
                          : optOutViolations.length
                            ? "The prospect asked to stop and the agent kept pitching. The number is suppressed anyway."
                            : "The prospect asked to stop, the agent stopped, and the number is suppressed."}
                      </div>
                      {optOutViolations.map((v, i) => (
                        <div className="quote" key={i}>
                          “{v.quote}”<span className="why">Said after the prospect asked not to be called.</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <details className="sentences">
                  <summary>How each of the agent&apos;s {detail.checks.classifications.length} sentences was classified</summary>
                  <div className="sentence-list">
                    {detail.checks.classifications.map((c, i) => (
                      <div className="verdict-row" key={i}>
                        <div>
                          <span className={`pill ${VERDICT_TONE[c.verdict] ?? "neutral"}`}>
                            {VERDICT_LABEL[c.verdict] ?? c.verdict}
                          </span>
                        </div>
                        <div>
                          <div className="s">“{c.sentence}”</div>
                          <div className="e">
                            {c.rule_id && <span className="r">{c.rule_id} · </span>}
                            {c.explanation}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}

            {/* 4. The record */}
            {phase === "done" && detail && prospect && (
              <div className={`step ${laterStep}`}>
                <div className="dot">4</div>
                <div className="step-head">
                  <h3>Written back to the record</h3>
                  <span className="meta">Structured, not a summary</span>
                </div>
                <p className="step-question">What happened, as data?</p>
                <dl className="record">
                  <div>
                    <dt>interest</dt>
                    <dd>{detail.outcome.interest.replace("_", " ")}</dd>
                  </div>
                  <div>
                    <dt>meeting_requested</dt>
                    <dd>
                      {String(detail.outcome.meeting_requested)}
                      {detail.outcome.meeting_preferences ? ` · ${detail.outcome.meeting_preferences}` : ""}
                    </dd>
                  </div>
                  <div>
                    <dt>has_news</dt>
                    <dd>{detail.outcome.has_news === null ? "unknown" : String(detail.outcome.has_news)}</dd>
                  </div>
                  <div>
                    <dt>opt_out_requested</dt>
                    <dd>{String(detail.outcome.opt_out_requested)}</dd>
                  </div>
                  <div>
                    <dt>disclosure_ok</dt>
                    <dd>{String(detail.checks.disclosure_ok)}</dd>
                  </div>
                  <div>
                    <dt>violations</dt>
                    <dd>{violations.length === 0 ? "none" : violations.map((v) => v.rule_id ?? v.code).join(", ")}</dd>
                  </div>
                  <div>
                    <dt>news_summary</dt>
                    <dd>{detail.outcome.news_summary ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>transcript_source</dt>
                    <dd>scenario</dd>
                  </div>
                </dl>
                <div className="record-actions">
                  <button className="btn small" onClick={saveToRecord}>
                    Save this call to {prospect.full_name.split(" ")[0]}&apos;s record
                  </button>
                  <span className="note">
                    {saved ?? "Runs the real gate at the real time, so it can refuse. One call per number per 24 hours."}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
