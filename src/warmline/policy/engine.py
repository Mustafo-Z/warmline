"""The pre-dial policy engine. SPEC 4.1, 4.2, 4.3.

Pure: no database, no network, no filesystem, no clock. The instant, the
history, the suppression list and the config all arrive as arguments. Nothing
here dials, and nothing here can be persuaded to.

Four properties the tests hold this to:

* **Total.** Bad data is a block reason, never an exception.
* **Fail closed.** A check that cannot be evaluated blocks.
* **Complete.** Every check runs; failures are reported together, not one per
  attempt.
* **Deterministic.** `primary_reason` comes from a fixed severity order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from warmline.phone import normalise_e164, region_for_e164
from warmline.policy import codes
from warmline.policy.models import (
    CheckOutcome,
    PolicyConfig,
    PolicyDecision,
    PreDialRequest,
)

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_LOOKAHEAD = 9  # enough to clear the longest run of non-permitted days


def evaluate_pre_dial(request: PreDialRequest, config: PolicyConfig) -> PolicyDecision:
    now = _as_utc(request.now)
    phone = normalise_e164(request.prospect.phone_e164)

    checks = (
        _number_verified(request, config, phone),
        _consent_present(request),
        _consent_unexpired(request, now),
        _consent_not_withdrawn(request),
        _number_not_suppressed(request, phone),
        _timezone_matches_prefix(request, config, phone),
        _inside_calling_hours(request, config, now),
        _within_attempt_limits(request, config, now, phone),
        _no_call_in_flight(request),
    )

    blocking = _blocking_reasons(checks, config.severity_order)

    return PolicyDecision(
        decision="block" if blocking else "allow",
        policy_version=config.policy_version,
        config_digest=config.config_digest,
        evaluated_at=now,
        prospect_id=request.prospect.id,
        phone_e164=phone or request.prospect.phone_e164,
        primary_reason=blocking[0] if blocking else None,
        blocking_reasons=blocking,
        checks=checks,
    )


def _blocking_reasons(
    checks: tuple[CheckOutcome, ...], severity: tuple[str, ...]
) -> tuple[str, ...]:
    """Blocking codes, deduplicated, most severe first.

    Deduplicated because several checks can fail for the same underlying reason
    — an unparseable number makes three of them unevaluable — and a caller
    reading the list wants distinct reasons, not repetition.
    """
    seen = {check.code for check in checks if check.result == "block"}
    ranked = sorted(
        seen, key=lambda code: severity.index(code) if code in severity else len(severity)
    )
    return tuple(ranked)


def _as_utc(value: datetime) -> datetime:
    """Naive input is read as UTC rather than rejected — the engine stays total."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _not_evaluable(check: str, reason: str, **detail: Any) -> CheckOutcome:
    """Fail closed, and say which check could not run and why (SPEC 4.1)."""
    return CheckOutcome(
        code=codes.CHECK_NOT_EVALUABLE,
        result="block",
        message=f"{check} could not be evaluated: {reason}.",
        recoverable="on_data_fix",
        detail={"check": check, "reason": reason, **detail},
    )


# --- the nine checks -------------------------------------------------------


def _number_verified(
    request: PreDialRequest, config: PolicyConfig, phone: str | None
) -> CheckOutcome:
    """SPEC 2.1 expressed as code, and the highest-severity reason there is."""
    if phone is None:
        return _not_evaluable(codes.NUMBER_NOT_VERIFIED, "the number is not valid E.164")

    entry = config.verified_numbers.get(phone)
    if entry is None:
        return CheckOutcome(
            code=codes.NUMBER_NOT_VERIFIED,
            result="block",
            message="Destination is not on the verified-number allowlist.",
            recoverable="never",
            detail={"verified_count": len(config.verified_numbers)},
        )

    return CheckOutcome(
        code=codes.NUMBER_NOT_VERIFIED,
        result="pass",
        detail={"matched_owner": entry.owner, "agreed_at": entry.agreed_at},
    )


def _consent_present(request: PreDialRequest) -> CheckOutcome:
    if request.consent is None:
        return CheckOutcome(
            code=codes.CONSENT_MISSING,
            result="block",
            message="No consent record for this prospect.",
            recoverable="on_data_fix",
            detail={},
        )
    return CheckOutcome(
        code=codes.CONSENT_MISSING,
        result="pass",
        detail={"lawful_basis": request.consent.lawful_basis},
    )


def _consent_unexpired(request: PreDialRequest, now: datetime) -> CheckOutcome:
    consent = request.consent
    if consent is None:
        # Absence is reported once, by CONSENT_MISSING. Reporting it twice would
        # make a single data gap look like two problems.
        return CheckOutcome(
            code=codes.CONSENT_EXPIRED,
            result="pass",
            detail={"reason": "no consent record; see CONSENT_MISSING"},
        )

    if consent.expires_at is None:
        return CheckOutcome(code=codes.CONSENT_EXPIRED, result="pass", detail={"expires_at": None})

    expires_at = _as_utc(consent.expires_at)
    if expires_at <= now:
        return CheckOutcome(
            code=codes.CONSENT_EXPIRED,
            result="block",
            message="Consent expired and has not been refreshed.",
            recoverable="on_data_fix",
            detail={"expires_at": _iso(expires_at), "now": _iso(now)},
        )

    return CheckOutcome(
        code=codes.CONSENT_EXPIRED, result="pass", detail={"expires_at": _iso(expires_at)}
    )


def _consent_not_withdrawn(request: PreDialRequest) -> CheckOutcome:
    consent = request.consent
    if consent is None or consent.withdrawn_at is None:
        return CheckOutcome(code=codes.CONSENT_WITHDRAWN, result="pass", detail={})

    return CheckOutcome(
        code=codes.CONSENT_WITHDRAWN,
        result="block",
        message="Consent was withdrawn. This is permanent.",
        recoverable="never",
        detail={"withdrawn_at": _iso(_as_utc(consent.withdrawn_at))},
    )


def _number_not_suppressed(request: PreDialRequest, phone: str | None) -> CheckOutcome:
    if phone is None:
        return _not_evaluable(codes.NUMBER_SUPPRESSED, "the number is not valid E.164")

    for entry in request.suppression:
        if normalise_e164(entry.phone_e164) == phone:
            return CheckOutcome(
                code=codes.NUMBER_SUPPRESSED,
                result="block",
                message="Number is on the suppression list.",
                recoverable="never",
                detail={
                    "suppression_reason": entry.reason,
                    "source": entry.source,
                    "note": entry.note,
                },
            )

    return CheckOutcome(code=codes.NUMBER_SUPPRESSED, result="pass", detail={})


def _timezone_matches_prefix(
    request: PreDialRequest, config: PolicyConfig, phone: str | None
) -> CheckOutcome:
    """A +1 number carrying Asia/Dubai would otherwise produce calls at 3am."""
    code = codes.TIMEZONE_PREFIX_MISMATCH
    tz_name = request.prospect.timezone

    if phone is None:
        return _not_evaluable(code, "the number is not valid E.164")

    number_country = region_for_e164(phone)
    if number_country is None:
        return _not_evaluable(code, "no country could be derived from the number")

    countries = config.timezone_countries.get(tz_name)
    if countries is None:
        return _not_evaluable(
            code,
            "the timezone is not in the policy's timezone_countries map",
            timezone=tz_name,
        )

    detail = {
        "timezone": tz_name,
        "number_country": number_country,
        "timezone_countries": list(countries),
    }

    if number_country in countries:
        return CheckOutcome(code=code, result="pass", detail=detail)

    return CheckOutcome(
        code=code,
        result=config.timezone_mismatch_action,
        message=(
            f"Number is a {number_country} number but the record says "
            f"{tz_name}. The calling-hours check cannot be trusted."
        ),
        recoverable="on_data_fix",
        detail=detail,
    )


def _inside_calling_hours(
    request: PreDialRequest, config: PolicyConfig, now: datetime
) -> CheckOutcome:
    code = codes.OUTSIDE_CALLING_HOURS
    prospect = request.prospect

    profile = config.profiles.get(prospect.region_profile)
    if profile is None:
        return _not_evaluable(
            code, "unknown region profile", region_profile=prospect.region_profile
        )

    try:
        tz = ZoneInfo(prospect.timezone)
    except (KeyError, ValueError, OSError):
        return _not_evaluable(code, "unknown timezone", timezone=prospect.timezone)

    local = now.astimezone(tz)
    local_day = _WEEKDAYS[local.weekday()]
    today = profile.window_for(local_day)
    window = (
        {"start": today[0].strftime("%H:%M"), "end": today[1].strftime("%H:%M")} if today else None
    )
    detail = {
        "timezone": prospect.timezone,
        "local_time": local.isoformat(),
        "local_day": local_day,
        "profile": profile.name,
        "window": window,
        "permitted_days": list(profile.days),
    }

    # Half-open, [start, end): 09:00:00 is inside, 18:00:00 is not. A day with
    # no window of its own is not a calling day at all.
    inside_window = today is not None and today[0] <= local.time() < today[1]

    if inside_window:
        return CheckOutcome(code=code, result="pass", detail=detail)

    reason = (
        f"{local_day} is not a permitted calling day"
        if today is None
        else f"local time {local:%H:%M} is outside {window['start']}-{window['end']}"
    )
    return CheckOutcome(
        code=code,
        result="block",
        message=f"In {prospect.timezone}, {reason} for the {profile.name} profile.",
        recoverable="after",
        retry_after=_next_window_open(local, profile, tz),
        detail=detail,
    )


def _next_window_open(local: datetime, profile, tz: ZoneInfo) -> datetime | None:
    """The next instant this check would pass, so the UI can say when."""
    for offset in range(_DAY_LOOKAHEAD):
        day = local.date() + timedelta(days=offset)
        window = profile.window_for(_WEEKDAYS[day.weekday()])
        if window is None:
            continue
        opens = datetime.combine(day, window[0], tzinfo=tz)
        if opens > local:
            return opens.astimezone(UTC)
    return None


def _within_attempt_limits(
    request: PreDialRequest, config: PolicyConfig, now: datetime, phone: str | None
) -> CheckOutcome:
    code = codes.ATTEMPT_LIMIT_REACHED
    limits = config.attempt_limits

    if phone is None:
        return _not_evaluable(code, "the number is not valid E.164")

    # Counted against the number, not the prospect record, so two rows sharing
    # a number cannot double the budget. Only calls that reached a provider
    # count: a call policy blocked cost the prospect nothing.
    reached = sorted(
        (
            _as_utc(attempt.dialed_at)
            for attempt in request.attempts
            if attempt.dialed_at is not None and normalise_e164(attempt.phone_e164) == phone
        ),
        reverse=True,
    )

    within_24h = [when for when in reached if when > now - timedelta(hours=24)]
    within_7d = [when for when in reached if when > now - timedelta(days=7)]

    detail = {
        "attempts_24h": len(within_24h),
        "limit_24h": limits.max_per_24h,
        "attempts_7d": len(within_7d),
        "limit_7d": limits.max_per_rolling_7d,
        "last_attempt_at": _iso(reached[0]) if reached else None,
    }

    retry_candidates = []
    if len(within_24h) >= limits.max_per_24h and limits.max_per_24h > 0:
        retry_candidates.append(within_24h[limits.max_per_24h - 1] + timedelta(hours=24))
    if len(within_7d) >= limits.max_per_rolling_7d and limits.max_per_rolling_7d > 0:
        retry_candidates.append(within_7d[limits.max_per_rolling_7d - 1] + timedelta(days=7))

    if not retry_candidates:
        return CheckOutcome(code=code, result="pass", detail=detail)

    return CheckOutcome(
        code=code,
        result="block",
        message=(
            f"{len(within_24h)} attempt(s) in the last 24h (limit {limits.max_per_24h}), "
            f"{len(within_7d)} in the last 7 days (limit {limits.max_per_rolling_7d})."
        ),
        recoverable="after",
        retry_after=max(retry_candidates),
        detail=detail,
    )


def _no_call_in_flight(request: PreDialRequest) -> CheckOutcome:
    """A concurrency guard, not a compliance rule: two clicks, one call."""
    for attempt in request.attempts:
        if (
            attempt.prospect_id == request.prospect.id
            and attempt.status in codes.IN_FLIGHT_STATUSES
        ):
            return CheckOutcome(
                code=codes.CALL_IN_FLIGHT,
                result="block",
                message="A call to this prospect is already in progress.",
                # No retry_after: the unblocking event is the call ending, which
                # is not a clock time we can compute from these inputs.
                recoverable="after",
                detail={"attempt_id": attempt.attempt_id, "status": attempt.status},
            )

    return CheckOutcome(code=codes.CALL_IN_FLIGHT, result="pass", detail={})
