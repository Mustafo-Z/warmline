"""E.164 normalisation, shared by storage, the policy engine and suppression.

SPEC 6.1: one normalisation function, used everywhere, so that
`+971 50 123 4567` and `+971501234567` are the same number to every part of
the system.
"""

from __future__ import annotations

import phonenumbers


def normalise_e164(raw: str | None) -> str | None:
    """Return the E.164 form of `raw`, or None if it is not a valid number.

    Strict on purpose: input must already carry a country code. Guessing a
    default region would mean guessing which country we are calling, and the
    calling-hours check depends on getting that right.
    """
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate.startswith("+"):
        return None
    try:
        parsed = phonenumbers.parse(candidate, None)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def region_for_e164(raw: str | None) -> str | None:
    """Return the ISO country code implied by the number's prefix, or None."""
    normalised = normalise_e164(raw)
    if normalised is None:
        return None
    try:
        parsed = phonenumbers.parse(normalised, None)
    except phonenumbers.NumberParseException:
        return None
    return phonenumbers.region_code_for_number(parsed)


def redact(phone_e164: str | None) -> str:
    """A form safe to put in a human-readable message (SPEC 4.3)."""
    if not phone_e164:
        return "(unknown number)"
    return f"{phone_e164[:-6]}…{phone_e164[-2:]}" if len(phone_e164) > 8 else "…"
