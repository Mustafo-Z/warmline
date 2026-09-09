"""Pre-dial reason codes and their severity order. SPEC 4.2, SPEC 4.3."""

from __future__ import annotations

NUMBER_NOT_VERIFIED = "NUMBER_NOT_VERIFIED"
CONSENT_MISSING = "CONSENT_MISSING"
CONSENT_EXPIRED = "CONSENT_EXPIRED"
CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"
NUMBER_SUPPRESSED = "NUMBER_SUPPRESSED"
TIMEZONE_PREFIX_MISMATCH = "TIMEZONE_PREFIX_MISMATCH"
OUTSIDE_CALLING_HOURS = "OUTSIDE_CALLING_HOURS"
ATTEMPT_LIMIT_REACHED = "ATTEMPT_LIMIT_REACHED"
CALL_IN_FLIGHT = "CALL_IN_FLIGHT"
CHECK_NOT_EVALUABLE = "CHECK_NOT_EVALUABLE"

#: Order in which `primary_reason` is chosen when several checks block.
#: Permanent blocks outrank recoverable ones, so the reason shown to a human is
#: the one that needs a human. Fixed here rather than derived from evaluation
#: order or dict iteration, so the answer is deterministic.
SEVERITY_ORDER: tuple[str, ...] = (
    NUMBER_NOT_VERIFIED,
    CONSENT_WITHDRAWN,
    NUMBER_SUPPRESSED,
    CONSENT_MISSING,
    CONSENT_EXPIRED,
    TIMEZONE_PREFIX_MISMATCH,
    CHECK_NOT_EVALUABLE,
    ATTEMPT_LIMIT_REACHED,
    OUTSIDE_CALLING_HOURS,
    CALL_IN_FLIGHT,
)

#: Statuses that mean a call is currently occupying the line for a prospect.
IN_FLIGHT_STATUSES = frozenset({"dialing", "in_progress"})
