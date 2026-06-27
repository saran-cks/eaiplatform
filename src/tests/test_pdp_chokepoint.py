"""DD-8 enforcement check: the action chokepoint has no bypass.

Static guard, in the spirit of test_architecture.py. No code path may invoke a
write-capable connector tool (``MCPConnectorPort.call_tool``) except via a PDP-guarded
module on the allowlist. There are zero such call sites today, so this passes — and it
will fail the moment someone wires ``.call_tool(...)`` without routing through the PDP,
forcing the chokepoint to be honoured before any tool execution code lands.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent

# Modules permitted to invoke a write-capable tool directly. Each MUST route via the PDP.
# Empty until the PDP-guarded MCP adapter is built; add it here (and only it) then.
_ALLOWLIST: frozenset[str] = frozenset()

# Matches an INVOCATION `x.call_tool(`, not the Protocol definition `async def call_tool(`.
_INVOKE = re.compile(r"\.call_tool\s*\(")


def test_no_write_tool_invocation_bypasses_the_pdp():
    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        rel = path.relative_to(SRC_ROOT).as_posix()
        if path.name.startswith("test_"):
            continue
        if _INVOKE.search(path.read_text(encoding="utf-8")) and rel not in _ALLOWLIST:
            offenders.append(rel)
    assert offenders == [], (
        "These modules invoke a write-capable tool outside the PDP chokepoint (DD-8). "
        f"Route them through PolicyDecisionPoint.decide() or add to the allowlist: {offenders}"
    )


def test_pdp_is_importable_and_default_denies_unknown_tools():
    """The chokepoint exists and its backbone (default-deny) is wired."""
    import asyncio

    from core.domain.policy.types import ActionRequest, DecisionEffect, PolicyRegistry
    from core.domain.value_objects.permission_scope import PermissionScope
    from core.use_cases.policy.policy_decision_point import PolicyDecisionPoint

    class _NullResolver:
        async def resolve(self, *, tool_name, arguments, scope):
            return None

    pdp = PolicyDecisionPoint(registry=PolicyRegistry(), target_resolver=_NullResolver())
    request = ActionRequest(tool_name="anything", scope=PermissionScope(tenant_id="t1"))
    decision = asyncio.run(pdp.decide(request))
    assert decision.effect is DecisionEffect.DENY
