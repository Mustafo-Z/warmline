"""Loading policy configuration from disk.

This is the I/O boundary. `src/warmline/policy/` stays pure: it is handed a
`PolicyConfig` and never reads a file (SPEC 4.1).
"""

from __future__ import annotations

import hashlib
from datetime import time
from pathlib import Path

import yaml

from warmline.phone import normalise_e164
from warmline.policy.models import (
    AttemptLimits,
    PolicyConfig,
    RegionProfile,
    VerifiedNumber,
)

POLICY_DIR = Path(__file__).resolve().parents[2] / "policy"

CALLING_WINDOWS = "calling_windows.yaml"
VERIFIED_NUMBERS = "verified_numbers.yaml"


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(hour=int(hours), minute=int(minutes))


def config_digest(paths: list[Path]) -> str:
    """SHA-256 over the policy files, so a stored decision names its config.

    SPEC 4.3: a decision made under an older policy version has to be
    distinguishable from a current one.
    """
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def load_policy_config(policy_dir: Path | None = None) -> PolicyConfig:
    directory = policy_dir or POLICY_DIR
    windows_path = directory / CALLING_WINDOWS
    numbers_path = directory / VERIFIED_NUMBERS

    windows = yaml.safe_load(windows_path.read_text())
    numbers = yaml.safe_load(numbers_path.read_text())

    profiles: dict[str, RegionProfile] = {}
    for name, raw in (windows.get("profiles") or {}).items():
        profiles[name] = RegionProfile(
            name=name,
            countries=tuple(raw["countries"]),
            days=tuple(day.lower() for day in raw["days"]),
            window_start=_parse_hhmm(raw["window"]["start"]),
            window_end=_parse_hhmm(raw["window"]["end"]),
        )

    verified: dict[str, VerifiedNumber] = {}
    for raw in numbers.get("numbers") or []:
        normalised = normalise_e164(raw["phone_e164"])
        if normalised is None:
            raise ValueError(
                f"verified_numbers.yaml carries an invalid number: {raw['phone_e164']}"
            )
        verified[normalised] = VerifiedNumber(
            phone_e164=normalised,
            owner=raw["owner"],
            agreed_at=str(raw["agreed_at"]),
        )

    limits = windows.get("attempt_limits") or {}

    return PolicyConfig(
        policy_version=str(windows["policy_version"]),
        config_digest=config_digest([windows_path, numbers_path]),
        default_profile=windows["default_profile"],
        profiles=profiles,
        attempt_limits=AttemptLimits(
            max_per_24h=int(limits["max_per_24h"]),
            max_per_rolling_7d=int(limits["max_per_rolling_7d"]),
        ),
        verified_numbers=verified,
        timezone_countries={
            tz: tuple(countries)
            for tz, countries in (windows.get("timezone_countries") or {}).items()
        },
        timezone_mismatch_action=windows.get("timezone_mismatch_action", "block"),
    )
