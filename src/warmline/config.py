"""Loading policy configuration from disk.

This is the I/O boundary. `src/warmline/policy/` stays pure: it is handed a
`PolicyConfig` and never reads a file (SPEC 4.1).
"""

from __future__ import annotations

import hashlib
import re
from datetime import time
from pathlib import Path

import yaml

from warmline.phone import normalise_e164
from warmline.policy.models import (
    AttemptLimits,
    ClaimsConfig,
    DisclosureConfig,
    NonClaimEligibility,
    PermittedClaim,
    PolicyConfig,
    RegionProfile,
    RulePattern,
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
            windows={
                day.lower(): (_parse_hhmm(hours["start"]), _parse_hhmm(hours["end"]))
                for day, hours in (raw["days"] or {}).items()
            },
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
        config_digest=config_digest([directory / name for name in POLICY_FILES]),
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


# --- the claim allowlist and the disclosure rule ---------------------------

PERMITTED_CLAIMS = "permitted_claims.yaml"
DISCLOSURE = "disclosure.yaml"

#: Every policy file, in the digest. A decision names the whole policy bundle
#: that produced it, not just the part its own checks happened to read.
POLICY_FILES = (CALLING_WINDOWS, VERIFIED_NUMBERS, PERMITTED_CLAIMS, DISCLOSURE)


def _rules(raw: list[dict] | None) -> tuple[RulePattern, ...]:
    return tuple(
        RulePattern(
            id=entry["id"],
            pattern=re.compile(entry["pattern"], re.IGNORECASE),
            reason=entry.get("reason"),
        )
        for entry in (raw or [])
    )


def load_claims_config(policy_dir: Path | None = None) -> ClaimsConfig:
    directory = policy_dir or POLICY_DIR
    raw = yaml.safe_load((directory / PERMITTED_CLAIMS).read_text())
    eligibility = raw.get("non_claim_eligibility") or {}

    return ClaimsConfig(
        policy_version=str(raw["policy_version"]),
        principal=raw["principal"],
        permitted_claims=tuple(
            PermittedClaim(
                id=entry["id"],
                canonical=entry["canonical"],
                may_paraphrase=bool(entry.get("may_paraphrase", False)),
            )
            for entry in raw.get("permitted_claims") or []
        ),
        prohibited_patterns=_rules(raw.get("prohibited_patterns")),
        non_claim_patterns=_rules(raw.get("non_claim_patterns")),
        commitment_patterns=_rules(raw.get("commitment_patterns")),
        opt_out_patterns=_rules(raw.get("opt_out_patterns")),
        paraphrase_threshold=float(raw.get("paraphrase_threshold", 0.7)),
        non_claim_eligibility=NonClaimEligibility(
            no_numeric_tokens=bool(eligibility.get("no_numeric_tokens", True)),
            no_proper_nouns_except_principal=bool(
                eligibility.get("no_proper_nouns_except_principal", True)
            ),
        ),
    )


def load_disclosure_config(policy_dir: Path | None = None) -> DisclosureConfig:
    directory = policy_dir or POLICY_DIR
    raw = yaml.safe_load((directory / DISCLOSURE).read_text())
    block = raw["disclosure"]

    return DisclosureConfig(
        policy_version=str(raw["policy_version"]),
        principal=raw["principal"],
        required_in_agent_turn=int(block["required_in_agent_turn"]),
        accepted_patterns=tuple(
            RulePattern(id=f"DISCLOSURE_{index}", pattern=re.compile(pattern, re.IGNORECASE))
            for index, pattern in enumerate(block["accepted_patterns"])
        ),
        must_also_mention_principal=bool(block.get("must_also_mention_principal", True)),
    )
