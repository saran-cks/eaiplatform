"""PdpGuardedMCPConnector — the action chokepoint (DD-8 + DD-11), and their first caller.

This is where the policy philosophy stops being paper. Every ``call_tool`` runs the same
deterministic gauntlet BEFORE the transport is touched:

    1. PDP.decide(ActionRequest)        — default-deny action policy (DD-8)
    2. TrajectoryMonitor.observe(event) — cumulative session risk over the sequence (DD-11)
    3. enforce verdicts                  — KILL > deny > require-approval > proceed
    4. transport.call_tool(...)          — reached ONLY on an ALLOW + non-KILL trajectory

The monitor is fed on *every* decision (including denies — that is the "probing" signal),
so a chain of individually-allowed reads can still escalate the session to KILL even though
each step passes the stateless PDP. This module is the sole entry on the static chokepoint
allowlist (``test_pdp_chokepoint.py``); the raw transport call below is legal precisely
because the PDP ran first.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from adapters.mcp.catalog import ToolCatalog
from adapters.mcp.transport import MCPTransportPort
from core.domain.policy.trajectory import ActionEvent, RiskLevel
from core.domain.policy.types import (
    ActionRequest,
    Effect,
    PolicyViolation,
    Reversibility,
    TrajectoryKill,
)
from core.domain.value_objects.permission_scope import PermissionScope
from core.ports.observability import ObsAttr, ObservabilityPort, SpanKind

if TYPE_CHECKING:
    from core.use_cases.policy.policy_decision_point import PolicyDecisionPoint
    from core.use_cases.policy.trajectory_monitor import TrajectoryMonitor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _noop_span():
    """Fallback when no ObservabilityPort is injected (keeps tests obs-free)."""
    yield None


class PdpGuardedMCPConnector:
    """MCPConnectorPort implementation that fronts every tool call with the PDP + monitor."""

    def __init__(
        self,
        *,
        catalog: ToolCatalog,
        pdp: PolicyDecisionPoint,
        monitor: TrajectoryMonitor,
        transport: MCPTransportPort,
        observability: ObservabilityPort | None = None,
    ) -> None:
        self._catalog = catalog
        self._pdp = pdp
        self._monitor = monitor
        self._transport = transport
        self._obs = observability

    def _span(self, name: str, attributes: Mapping[str, Any]):
        if self._obs is None:
            return _noop_span()
        return self._obs.span(name, kind=SpanKind.TOOL, attributes=attributes)

    async def connect(self, *, server: str, tenant_id: str) -> None:
        # Mock transport is sessionless; real MCP transport will open a session here.
        logger.debug("MCP connect requested (server=%s tenant=%s)", server, tenant_id)

    async def list_tools(self, *, scope: PermissionScope) -> Sequence[Mapping[str, Any]]:
        return self._catalog.list_for_scope(scope)

    async def call_tool(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
        scope: PermissionScope,
        session_id: str | None = None,
    ) -> Mapping[str, Any]:
        sid = session_id or scope.subject_id or scope.tenant_id
        spec = self._catalog.get(name)

        # 1. PDP — deterministic, default-deny. Unknown tool (spec is None) → DENY inside.
        request = ActionRequest(tool_name=name, scope=scope, arguments=arguments)
        decision = await self._pdp.decide(request)

        # 2. Trajectory monitor — fed on EVERY decision so denies count as probing (DD-11).
        spec_kind = spec.target_kind if spec else ""
        event = ActionEvent(
            effect=spec.effect if spec else Effect.READ,
            reversibility=spec.reversibility if spec else Reversibility.REVERSIBLE,
            environment=decision.target.environment if decision.target else "dev",
            decision=decision.effect,
            data_sources=request.data_sources,
            required_permissions=spec.required_permissions if spec else frozenset(),
            target_kind=decision.target.kind if decision.target else spec_kind,
        )
        verdict = await self._monitor.observe_async(sid, event)

        # Forensic span (DD-8/DD-11): one TOOL span carries the decision, the cumulative
        # session risk, and the outcome — denied/killed calls record an ERROR span too.
        server = self._catalog.server_for(name) or "unknown"
        attributes: dict[str, Any] = {
            ObsAttr.TOOL_NAME: name,
            ObsAttr.TOOL_SERVER: server,
            ObsAttr.TOOL_ARGUMENTS: dict(arguments),
            ObsAttr.SESSION_ID: sid,
            ObsAttr.TENANT_ID: scope.tenant_id,
            ObsAttr.POLICY_DECISION: decision.effect.value,
            ObsAttr.POLICY_REASON: decision.reason,
            ObsAttr.POLICY_ENVIRONMENT: event.environment,
            ObsAttr.POLICY_TARGET: decision.target.resource_id if decision.target else None,
            ObsAttr.RISK_LEVEL: verdict.level.value,
            ObsAttr.RISK_SCORE: verdict.risk,
            ObsAttr.RISK_SIGNALS: list(verdict.signals),
        }

        async with self._span(f"mcp.tool.{name}", attributes) as span:
            # 3. Enforce, strongest veto first.
            if verdict.level is RiskLevel.KILL:
                logger.warning(
                    "MCP call '%s' killed by trajectory monitor (session=%s risk=%.2f signals=%s)",
                    name, sid, verdict.risk, verdict.signals,
                )
                raise TrajectoryKill(
                    f"session {sid} risk {verdict.risk:.2f} crossed KILL "
                    f"({', '.join(verdict.signals)})"
                )
            if not decision.allowed:
                logger.warning("MCP call '%s' denied by PDP: %s", name, decision.reason)
                raise PolicyViolation(decision.reason)
            if verdict.level is RiskLevel.REQUIRE_APPROVAL:
                logger.warning(
                    "MCP call '%s' needs re-approval by trajectory monitor (session=%s risk=%.2f)",
                    name, sid, verdict.risk,
                )
                raise PolicyViolation(
                    f"trajectory risk {verdict.risk:.2f} requires re-approval"
                )

            # 4. Cleared. Now — and only now — touch the external transport.
            logger.info("MCP call '%s' ALLOWED (session=%s risk=%.2f)", name, sid, verdict.risk)
            result = await self._transport.call_tool(
                server=server, name=name, arguments=arguments
            )
            if span is not None:
                span.set_attribute(ObsAttr.OUTPUT, result.get("result", result))
            return result

    async def disconnect(self, *, server: str, tenant_id: str) -> None:
        logger.debug("MCP disconnect requested (server=%s tenant=%s)", server, tenant_id)

    async def close(self) -> None:
        await self._transport.close()
