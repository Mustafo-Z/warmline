"""Value types for the pre-dial policy engine. SPEC 4.1, 4.3.

Everything here is frozen and I/O-free. The engine is handed these; it never
goes and fetches them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Literal

from warmline.policy.codes import SEVERITY_ORDER

CheckResult = Literal["pass", "block", "warn"]
Recoverable = Literal["never", "on_data_fix", "after"]
Decision = Literal["allow", "block"]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Consent:
    lawful_basis: str
    captured_at: datetime
    expires_at: datetime | None = None
    withdrawn_at: datetime | None = None
    evidence: str = ""


@dataclass(frozen=True)
class SuppressionEntry:
    phone_e164: str
    reason: str
    source: str = "seed"
    note: str | None = None


@dataclass(frozen=True)
class AttemptRecord:
    """One past or in-flight call attempt.

    `dialed_at` is None for attempts that policy blocked. Those do not consume
    attempt budget (SPEC 4.2) — only calls that reached a provider count.
    """

    attempt_id: str
    prospect_id: str
    phone_e164: str
    status: str
    requested_at: datetime
    dialed_at: datetime | None = None


@dataclass(frozen=True)
class Prospect:
    id: str
    phone_e164: str
    timezone: str
    region_profile: str


@dataclass(frozen=True)
class PreDialRequest:
    prospect: Prospect
    now: datetime
    consent: Consent | None = None
    suppression: tuple[SuppressionEntry, ...] = ()
    attempts: tuple[AttemptRecord, ...] = ()


@dataclass(frozen=True)
class RegionProfile:
    """A calling policy for one region, with a window per working day.

    Per day rather than one window plus a list of days: a working week is not
    always uniform. The UAE's Friday is a half day, and a single window would
    mean either calling people on Friday afternoon or not calling them on
    Friday at all.
    """

    name: str
    countries: tuple[str, ...]
    #: Day abbreviation ("mon") to (start, end). A day absent from this mapping
    #: is not a calling day.
    windows: dict[str, tuple[time, time]]

    @property
    def days(self) -> tuple[str, ...]:
        order = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
        return tuple(day for day in order if day in self.windows)

    def window_for(self, day: str) -> tuple[time, time] | None:
        return self.windows.get(day)


@dataclass(frozen=True)
class AttemptLimits:
    max_per_24h: int
    max_per_rolling_7d: int


@dataclass(frozen=True)
class VerifiedNumber:
    phone_e164: str
    owner: str
    agreed_at: str


@dataclass(frozen=True)
class PolicyConfig:
    policy_version: str
    config_digest: str
    default_profile: str
    profiles: dict[str, RegionProfile]
    attempt_limits: AttemptLimits
    verified_numbers: dict[str, VerifiedNumber]
    timezone_countries: dict[str, tuple[str, ...]]
    timezone_mismatch_action: Literal["block", "warn"] = "block"
    severity_order: tuple[str, ...] = SEVERITY_ORDER


@dataclass(frozen=True)
class CheckOutcome:
    code: str
    result: CheckResult
    message: str | None = None
    recoverable: Recoverable | None = None
    retry_after: datetime | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "result": self.result}
        if self.message is not None:
            out["message"] = self.message
        if self.recoverable is not None:
            out["recoverable"] = self.recoverable
        if self.retry_after is not None:
            out["retry_after"] = _iso(self.retry_after)
        out["detail"] = dict(self.detail)
        return out


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    policy_version: str
    config_digest: str
    evaluated_at: datetime
    prospect_id: str
    phone_e164: str
    primary_reason: str | None
    blocking_reasons: tuple[str, ...]
    checks: tuple[CheckOutcome, ...]

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def to_dict(self) -> dict[str, Any]:
        """The shape in SPEC 4.3, stored verbatim and returned verbatim."""
        return {
            "decision": self.decision,
            "policy_version": self.policy_version,
            "config_digest": self.config_digest,
            "evaluated_at": _iso(self.evaluated_at),
            "prospect_id": self.prospect_id,
            "phone_e164": self.phone_e164,
            "primary_reason": self.primary_reason,
            "blocking_reasons": list(self.blocking_reasons),
            "checks": [check.to_dict() for check in self.checks],
        }


# --- the claim allowlist (SPEC 5.1) ----------------------------------------


@dataclass(frozen=True)
class PermittedClaim:
    id: str
    canonical: str
    may_paraphrase: bool


@dataclass(frozen=True)
class RulePattern:
    """A named, compiled pattern. The id travels with every violation so that a
    reviewer can see which rule fired without re-deriving it."""

    id: str
    pattern: re.Pattern[str]
    reason: str | None = None


@dataclass(frozen=True)
class NonClaimEligibility:
    no_numeric_tokens: bool
    no_proper_nouns_except_principal: bool


@dataclass(frozen=True)
class ClaimsConfig:
    policy_version: str
    principal: str
    permitted_claims: tuple[PermittedClaim, ...]
    prohibited_patterns: tuple[RulePattern, ...]
    non_claim_patterns: tuple[RulePattern, ...]
    non_claim_eligibility: NonClaimEligibility
    commitment_patterns: tuple[RulePattern, ...] = ()
    opt_out_patterns: tuple[RulePattern, ...] = ()
    paraphrase_threshold: float = 0.7

    def claim(self, claim_id: str) -> PermittedClaim | None:
        return next((c for c in self.permitted_claims if c.id == claim_id), None)


@dataclass(frozen=True)
class DisclosureConfig:
    policy_version: str
    principal: str
    required_in_agent_turn: int
    accepted_patterns: tuple[RulePattern, ...]
    must_also_mention_principal: bool
