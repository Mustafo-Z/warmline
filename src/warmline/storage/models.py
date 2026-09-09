"""Row types for tables whose shape is wider than the policy engine needs.

Consent, SuppressionEntry and AttemptRecord already have exactly the right
shape in warmline.policy.models, so storage reuses those rather than defining
near-identical twins. Only the prospect row is wider: the engine needs four
fields from it, the UI needs the rest.
"""

from __future__ import annotations

from dataclasses import dataclass

from warmline.policy.models import Prospect


@dataclass(frozen=True)
class ProspectRecord:
    id: str
    full_name: str
    company: str
    role: str | None
    phone_e164: str
    timezone: str
    region_profile: str
    language: str
    is_fixture: bool

    def to_policy(self) -> Prospect:
        """The projection the policy engine is given. SPEC 4.1."""
        return Prospect(
            id=self.id,
            phone_e164=self.phone_e164,
            timezone=self.timezone,
            region_profile=self.region_profile,
        )
