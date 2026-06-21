"""The permission gate — ADR-0005's daemon-owned, default-closed authorizer.

The model only ever *proposes* a skill; the daemon (Brain) asks this authorizer
whether the current principal may run it, then executes or refuses. The gate —
never the model — is the trust boundary, so a coaxed or injected model can never
elevate past a proposal.

v1 policy is the coarse ``operator_only`` capability: a privileged skill is
authorized only for the operator principal. The full principal × assurance ×
grant model (ADR-0005) layers in here — extend ``AuthzContext`` and
``Authorizer.authorize`` — without moving the call site on the daemon spine.
"""
from __future__ import annotations

from dataclasses import dataclass

from .skills import is_operator_only


@dataclass
class AuthzContext:
    """Who is asking — and, later, how sure we are + what they've been granted.

    v1 carries only ``is_operator``. The caller resolves it **default-closed**:
    a far or unknown speaker on a live call is NOT the operator.
    """
    is_operator: bool
    # future (ADR-0005): assurance tier, active grants, audience, …


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    # future (ADR-0005): needs_keyboard_confirm: bool = False


class Authorizer:
    """Default-closed permission gate. Owned by the daemon, never the model."""

    def authorize(self, skill: object, ctx: AuthzContext) -> Decision:
        if is_operator_only(skill) and not ctx.is_operator:
            return Decision(False, "operator-only")
        return Decision(True)
