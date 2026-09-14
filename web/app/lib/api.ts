// Types and helpers shared by the page. Every shape here mirrors a response
// from the FastAPI service; nothing is invented on this side.

export const API = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export const REPO = "https://github.com/Mustafo-Z/warmline";

export type CheckResult = "pass" | "block" | "warn";

export type Check = {
  code: string;
  result: CheckResult;
  message?: string;
  recoverable?: "never" | "on_data_fix" | "after";
  retry_after?: string;
  detail: Record<string, unknown>;
};

export type Decision = {
  decision: "allow" | "block";
  policy_version: string;
  config_digest: string;
  evaluated_at: string;
  prospect_id: string;
  primary_reason: string | null;
  blocking_reasons: string[];
  checks: Check[];
};

export type Violation = {
  code: string;
  rule_id: string | null;
  turn_index: number;
  quote: string;
  tier: string;
};

export type Classification = {
  turn_index: number;
  sentence: string;
  verdict: string;
  rule_id: string | null;
  explanation: string;
};

export type Turn = { index: number; role: "agent" | "prospect"; text: string };

export type ScenarioSummary = { id: string; label: string; description: string };

// What the checkers make of one conversation. Scripted and live conversations
// come back in this same shape, and the page renders both with the same parts.
export type Review = {
  transcript: { turns: Turn[]; source?: string };
  checks: {
    disclosure_ok: boolean;
    violations: Violation[];
    classifications: Classification[];
    opt_out_requested: boolean;
    ended_during_opening?: boolean;
  };
  outcome: {
    interest: string;
    has_news: boolean | null;
    news_summary: string | null;
    meeting_requested: boolean;
    meeting_preferences: string | null;
    opt_out_requested: boolean;
  };
};

export type ScenarioDetail = ScenarioSummary & Review;

export type VoiceStatus = { enabled: boolean; max_duration_seconds: number; reason: string | null };

export type VoiceIssued = {
  conversation_token: string;
  conversation_id: string;
  max_duration_seconds: number;
};

export type VoiceResult = Review & { conversation_id: string; processed_at: string };

export type StoredOutcome = {
  interest: string;
  disclosure_ok: boolean;
  meeting_requested: boolean;
  opt_out_requested: boolean;
  violations: Violation[];
  transcript_source: string;
  news_summary: string | null;
  processed_at: string;
};

export type Prospect = {
  id: string;
  full_name: string;
  company: string;
  role: string | null;
  phone_e164: string;
  timezone: string;
  is_fixture: boolean;
  last_outcome: StoredOutcome | null;
};

export type Health = {
  status: string;
  policy_version: string;
  config_digest: string;
  provider: string;
  places_real_calls: boolean;
};

export type SentenceVerdict = {
  sentence: string;
  verdict: string;
  rule_id: string | null;
  explanation: string;
};

export async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

export async function postJSON<T>(path: string, body: unknown): Promise<{ status: number; body: T }> {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: response.status, body: await response.json() };
}

// Each pre-dial check phrased as the condition that has to hold, so a passing
// check reads as a true statement and a failing one reads as what went wrong.
export const CHECK_LABELS: Record<string, string> = {
  NUMBER_NOT_VERIFIED: "Number is on the verified allowlist",
  CONSENT_MISSING: "A consent record exists",
  CONSENT_EXPIRED: "Consent has not expired",
  CONSENT_WITHDRAWN: "Consent has not been withdrawn",
  NUMBER_SUPPRESSED: "Number is not on the suppression list",
  TIMEZONE_PREFIX_MISMATCH: "Timezone matches the number's country",
  OUTSIDE_CALLING_HOURS: "Inside local calling hours",
  ATTEMPT_LIMIT_REACHED: "Under the attempt limit",
  CALL_IN_FLIGHT: "No call already in progress",
  CHECK_NOT_EVALUABLE: "Every check could be evaluated",
};

export const REASON_SHORT: Record<string, string> = {
  NUMBER_NOT_VERIFIED: "Number not on the verified allowlist",
  CONSENT_MISSING: "No consent record",
  CONSENT_EXPIRED: "Consent expired",
  CONSENT_WITHDRAWN: "Consent withdrawn",
  NUMBER_SUPPRESSED: "Number suppressed",
  TIMEZONE_PREFIX_MISMATCH: "Timezone does not match number",
  OUTSIDE_CALLING_HOURS: "Outside calling hours",
  ATTEMPT_LIMIT_REACHED: "Attempt limit reached",
  CALL_IN_FLIGHT: "Call already in progress",
  CHECK_NOT_EVALUABLE: "A check could not run",
};

export const VERDICT_LABEL: Record<string, string> = {
  prohibited: "Prohibited",
  commitment: "Out of scope",
  unclassified: "Unclassified",
  permitted: "Permitted",
  non_claim: "Not a claim",
};

export const VERDICT_TONE: Record<string, "ok" | "bad" | "warn" | "neutral"> = {
  prohibited: "bad",
  commitment: "bad",
  unclassified: "warn",
  permitted: "ok",
  non_claim: "neutral",
};

export function formatInZone(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone,
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function zoneLabel(timeZone: string): string {
  return timeZone.split("/").pop()?.replace("_", " ") ?? timeZone;
}
