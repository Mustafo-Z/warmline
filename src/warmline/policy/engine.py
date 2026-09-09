"""The pre-dial policy engine. SPEC 4.1, 4.2, 4.3.

Not implemented yet — the tests come first.
"""

from __future__ import annotations

from warmline.policy.models import PolicyConfig, PolicyDecision, PreDialRequest


def evaluate_pre_dial(request: PreDialRequest, config: PolicyConfig) -> PolicyDecision:
    raise NotImplementedError("SPEC 4.2 — implemented in the following commit")
