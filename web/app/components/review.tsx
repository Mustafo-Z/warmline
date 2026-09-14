"use client";

// The parts of a finished conversation that look the same whether it was
// scripted or live: the transcript with offending sentences marked, the
// post-call checks, and the structured record.

import type { ReactNode } from "react";
import { VERDICT_LABEL, VERDICT_TONE, type Review, type Turn, type Violation } from "../lib/api";

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

type TranscriptProps = {
  turns: Turn[];
  violations?: Violation[];
  agentLabel: string;
  prospectLabel: string;
  pending?: boolean;
};

export function TranscriptView({ turns, violations = [], agentLabel, prospectLabel, pending }: TranscriptProps) {
  return (
    <div className="chat">
      {turns.map((turn) => {
        const flags = violations.filter((v) => v.turn_index === turn.index && QUOTABLE.has(v.code));
        return (
          <div key={turn.index} className={`bubble-row ${turn.role}`}>
            <div className="bubble">
              <span className="who">{turn.role === "agent" ? agentLabel : prospectLabel}</span>
              {highlight(turn.text, flags)}
            </div>
          </div>
        );
      })}
      {pending && (
        <div className="typing">
          <span>●</span> <span>●</span> <span>●</span>
        </div>
      )}
    </div>
  );
}

export function PostCallChecks({ review, hasNumber }: { review: Review; hasNumber: boolean }) {
  const { checks } = review;
  const claims = checks.violations.filter((v) => v.code === "UNPERMITTED_CLAIM");
  const commitments = checks.violations.filter((v) => v.code === "OUT_OF_SCOPE_COMMITMENT");
  const optOuts = checks.violations.filter((v) => v.code === "OPT_OUT_NOT_HONOURED");
  const explain = (quote: string) => checks.classifications.find((c) => c.sentence === quote)?.explanation ?? "";

  const optOutText = !checks.opt_out_requested
    ? "The prospect did not ask to stop."
    : optOuts.length
      ? `The prospect asked to stop and the agent kept pitching.${hasNumber ? " The number is suppressed anyway." : ""}`
      : `The prospect asked to stop and the agent stopped.${hasNumber ? " The number is suppressed." : ""}`;

  return (
    <>
      <div className="results">
        <div className="result">
          <span className={`icon ${checks.disclosure_ok ? "ok" : "bad"}`}>{checks.disclosure_ok ? "✓" : "✕"}</span>
          <div>
            <div className="title">Disclosed that it is an AI, in its first turn</div>
            {!checks.disclosure_ok && (
              <div className="sub">
                {checks.violations.find((v) => v.code.startsWith("DISCLOSURE"))?.code} — the prospect was not told they
                were talking to an AI.
              </div>
            )}
          </div>
        </div>

        <div className="result">
          <span className={`icon ${claims.length ? "bad" : "ok"}`}>{claims.length ? "✕" : "✓"}</span>
          <div>
            <div className="title">Every claim is on the approved list</div>
            {claims.map((v, i) => (
              <div className="quote" key={i}>
                “{v.quote}”
                <span className="why">
                  {v.rule_id} · {explain(v.quote)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="result">
          <span className={`icon ${commitments.length ? "bad" : "ok"}`}>{commitments.length ? "✕" : "✓"}</span>
          <div>
            <div className="title">Made no commitment it had no authority to make</div>
            {commitments.map((v, i) => (
              <div className="quote" key={i}>
                “{v.quote}”
                <span className="why">
                  {v.rule_id} · {explain(v.quote)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="result">
          <span className={`icon ${!checks.opt_out_requested ? "neutral" : optOuts.length ? "bad" : "ok"}`}>
            {!checks.opt_out_requested ? "–" : optOuts.length ? "✕" : "✓"}
          </span>
          <div>
            <div className="title">Honoured an opt-out</div>
            <div className="sub">{optOutText}</div>
            {optOuts.map((v, i) => (
              <div className="quote" key={i}>
                “{v.quote}”<span className="why">Said after the prospect asked not to be called.</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <details className="sentences">
        <summary>How each of the agent&apos;s {checks.classifications.length} sentences was classified</summary>
        <div className="sentence-list">
          {checks.classifications.map((c, i) => (
            <div className="verdict-row" key={i}>
              <div>
                <span className={`pill ${VERDICT_TONE[c.verdict] ?? "neutral"}`}>{VERDICT_LABEL[c.verdict] ?? c.verdict}</span>
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
    </>
  );
}

export function RecordGrid({
  review,
  source,
  children,
}: {
  review: Review;
  source: "scenario" | "live";
  children?: ReactNode;
}) {
  const { outcome, checks } = review;
  return (
    <>
      <dl className="record">
        <div>
          <dt>interest</dt>
          <dd>{outcome.interest.replace("_", " ")}</dd>
        </div>
        <div>
          <dt>meeting_requested</dt>
          <dd>
            {String(outcome.meeting_requested)}
            {outcome.meeting_preferences ? ` · ${outcome.meeting_preferences}` : ""}
          </dd>
        </div>
        <div>
          <dt>has_news</dt>
          <dd>{outcome.has_news === null ? "unknown" : String(outcome.has_news)}</dd>
        </div>
        <div>
          <dt>opt_out_requested</dt>
          <dd>{String(outcome.opt_out_requested)}</dd>
        </div>
        <div>
          <dt>disclosure_ok</dt>
          <dd>{String(checks.disclosure_ok)}</dd>
        </div>
        <div>
          <dt>violations</dt>
          <dd>{checks.violations.length === 0 ? "none" : checks.violations.map((v) => v.rule_id ?? v.code).join(", ")}</dd>
        </div>
        <div>
          <dt>news_summary</dt>
          <dd>{outcome.news_summary ?? "—"}</dd>
        </div>
        <div>
          <dt>transcript_source</dt>
          <dd>{source}</dd>
        </div>
      </dl>
      {children}
    </>
  );
}
