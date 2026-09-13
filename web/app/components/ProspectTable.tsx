"use client";

import { REASON_SHORT, formatInZone, zoneLabel, type Decision, type Prospect } from "../lib/api";

type Props = {
  prospects: Prospect[];
  live: Record<string, Decision>;
  selected: string;
  onWalkThrough: (id: string) => void;
};

export function ProspectTable({ prospects, live, selected, onWalkThrough }: Props) {
  return (
    <div className="card table-wrap">
      <table>
        <thead>
          <tr>
            <th>Prospect</th>
            <th>Number</th>
            <th>Can we call now?</th>
            <th>Last call on record</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {prospects.map((p) => {
            const decision = live[p.id];
            const primary = decision?.primary_reason ?? "";
            const message = decision?.checks.find((c) => c.code === primary)?.message;
            const outcome = p.last_outcome;
            return (
              <tr key={p.id} className={p.id === selected ? "selected" : ""}>
                <td>
                  <div className="name">{p.full_name}</div>
                  <div className="sub">
                    {p.company}
                    {p.role ? ` · ${p.role}` : ""}
                  </div>
                  {p.is_fixture && (
                    <div style={{ marginTop: 6 }}>
                      <span className="tag">Fictional</span>
                    </div>
                  )}
                </td>
                <td>
                  <div className="mono">{p.phone_e164}</div>
                  <div className="sub">{zoneLabel(p.timezone)}</div>
                </td>
                <td>
                  {!decision ? (
                    <span className="pill neutral">Checking…</span>
                  ) : decision.decision === "allow" ? (
                    <span className="pill ok">
                      <span className="d" />
                      Callable now
                    </span>
                  ) : (
                    <>
                      <span className="pill bad">
                        <span className="d" />
                        {REASON_SHORT[primary] ?? primary}
                      </span>
                      {message && <div className="reason">{message}</div>}
                      {decision.blocking_reasons.length > 1 && (
                        <div className="reason">
                          and {decision.blocking_reasons.length - 1} more failing check
                          {decision.blocking_reasons.length > 2 ? "s" : ""}
                        </div>
                      )}
                    </>
                  )}
                </td>
                <td>
                  {!outcome ? (
                    <span className="sub">No calls yet</span>
                  ) : (
                    <>
                      <div>
                        {outcome.interest.replace("_", " ")}
                        {outcome.meeting_requested ? " · meeting requested" : ""}
                        {outcome.opt_out_requested ? " · opted out" : ""}
                      </div>
                      {outcome.violations.length > 0 ? (
                        <div style={{ marginTop: 4 }}>
                          {outcome.violations.map((v, i) => (
                            <span key={i} className="pill bad" style={{ marginRight: 4 }}>
                              {v.rule_id ?? v.code}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <div className="reason">No violations</div>
                      )}
                      <div className="reason">
                        <span className="tag">Simulated</span> {formatInZone(outcome.processed_at, p.timezone)}
                      </div>
                    </>
                  )}
                </td>
                <td style={{ textAlign: "right" }}>
                  <button className="btn small" onClick={() => onWalkThrough(p.id)}>
                    Walk through
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
