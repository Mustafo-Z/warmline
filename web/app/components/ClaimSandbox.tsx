"use client";

import { useEffect, useState } from "react";
import { VERDICT_LABEL, VERDICT_TONE, postJSON, type SentenceVerdict } from "../lib/api";

const EXAMPLES = [
  "We work with companies on press coverage.",
  "Our retainers start at 5000 dollars a month.",
  "We can get you into Forbes.",
  "We work with 400 companies, do you have news?",
  "Yes, I can do that. I'll send the contract over.",
  "We work with over four hundred companies.",
];

export function ClaimSandbox() {
  const [text, setText] = useState(EXAMPLES[1]);
  const [result, setResult] = useState<SentenceVerdict[]>([]);

  useEffect(() => {
    const pending = setTimeout(async () => {
      if (!text.trim()) {
        setResult([]);
        return;
      }
      try {
        const { body } = await postJSON<{ sentences: SentenceVerdict[] }>("/claims/check", { text });
        setResult(body.sentences);
      } catch {
        setResult([]);
      }
    }, 220);
    return () => clearTimeout(pending);
  }, [text]);

  return (
    <div className="card sandbox">
      <div className="sandbox-input">
        <div className="field">
          <label htmlFor="sandbox">Something the agent might say</label>
          <textarea
            id="sandbox"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="We can get you on the front page by next week."
          />
        </div>
        <div className="chips">
          {EXAMPLES.map((example) => (
            <button key={example} className="chip" onClick={() => setText(example)}>
              {example}
            </button>
          ))}
        </div>
        <p className="channel-note">
          The checker works on text, not audio. The same rules would apply to an SMS, WhatsApp message or
          email — and there they can run <em>before</em> the message is sent, which is a stronger control than
          flagging a call after it has ended.
        </p>
      </div>

      <div className="sandbox-output">
        <div className="eyebrow" style={{ marginBottom: 6 }}>
          Tier 1 verdict, per sentence
        </div>
        {result.length === 0 ? (
          <p style={{ color: "var(--ink-3)" }}>Type something, or pick an example.</p>
        ) : (
          result.map((r, i) => (
            <div className="verdict-row" key={i}>
              <div>
                <span className={`pill ${VERDICT_TONE[r.verdict] ?? "neutral"}`}>
                  <span className="d" />
                  {VERDICT_LABEL[r.verdict] ?? r.verdict}
                </span>
              </div>
              <div>
                <div className="s">“{r.sentence}”</div>
                <div className="e">
                  {r.rule_id && <span className="r">{r.rule_id} · </span>}
                  {r.explanation}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
