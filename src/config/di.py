"""Dependency injection — the ONLY place concrete adapters are bound to ports.

Each provider returns the adapter implementing one port. Until an adapter is built
its provider raises ``AdapterNotWired`` (real, explicit behaviour — not a placeholder)
naming the session that delivers it. When you implement an adapter, replace the single
raise with the construction line, e.g.::

    @cached_property
    def store(self) -> StorePort:
        from adapters.store.postgres import PostgresAdapter
        return PostgresAdapter(self._settings)

Nothing else in the codebase may import adapters. Routes/use-cases receive ports
from this container only.
"""

from __future__ import annotations

from functools import cached_property

from config.settings import Settings, get_settings
from core.domain.agent_control import AgentKillRegistry
from core.ports.agent import AgentPort
from core.ports.cache import CachePort
from core.ports.guard import GuardPort
from core.ports.llm import LLMPort
from core.ports.mcp_connector import MCPConnectorPort
from core.ports.observability import ObservabilityPort
from core.ports.queue import QueuePort
from core.ports.retriever import RetrieverPort
from core.ports.store import StorePort


class AdapterNotWired(NotImplementedError):
    """Raised when a port is requested before its adapter has been implemented/bound."""


class Container:
    """Holds settings and lazily constructs one adapter per port (singleton per container)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings

    # --- storage (Session 3) ---
    @cached_property
    def store(self) -> StorePort:
        from adapters.store.postgres import PostgresAdapter
        return PostgresAdapter(self._settings)

    @cached_property
    def cache(self) -> CachePort:
        from adapters.cache.valkey import ValkeyAdapter
        return ValkeyAdapter(self._settings)

    # --- retrieval (Session 4) ---
    @cached_property
    def retriever(self) -> RetrieverPort:
        from adapters.retriever.qdrant import QdrantRetrieverAdapter
        return QdrantRetrieverAdapter(self._settings)

    # --- chat (Session 5) ---
    @cached_property
    def llm(self) -> LLMPort:
        from adapters.llm.bedrock import BedrockAdapter
        return BedrockAdapter(self._settings)

    # --- prompt guard (input screening; chat + agent front door) ---
    @cached_property
    def guard(self) -> GuardPort:
        if not self._settings.guard_enabled:
            from adapters.guard.null_guard import NullGuardAdapter
            return NullGuardAdapter()
        from adapters.guard.http_guard import HttpGuardAdapter
        return HttpGuardAdapter(self._settings)

    # --- agent (Session 6) ---
    @cached_property
    def agent_kill_registry(self) -> AgentKillRegistry:
        """Shared DD-11 kill ledger: written by the runner, drained by the agent_reaper."""
        return AgentKillRegistry()

    @cached_property
    def agent(self) -> AgentPort:
        from adapters.agent.a2a.registry import PeerRegistry
        from adapters.agent.langgraph_runner import LangGraphRunner
        registry = PeerRegistry()
        # The agent runtime is the first runtime caller of the PDP chokepoint: its workers
        # fetch external data through self.mcp (DD-8/DD-11). A KILL is recorded in the shared
        # registry the reaper drains.
        return LangGraphRunner(
            self._settings,
            self.llm,
            peer_registry=registry,
            mcp=self.mcp,
            kill_registry=self.agent_kill_registry,
        )

    # --- MCP (Session 7) — PDP-guarded; first real caller of DD-8 + DD-11 ---
    @cached_property
    def mcp(self) -> MCPConnectorPort:
        from adapters.mcp.catalog import ToolCatalog, build_catalog
        from adapters.mcp.connector import PdpGuardedMCPConnector
        from adapters.mcp.target_resolver import McpTargetResolver
        from adapters.mcp.transport import MockMCPTransport
        from core.use_cases.policy.policy_decision_point import PolicyDecisionPoint
        from core.use_cases.policy.trajectory_monitor import TrajectoryMonitor

        # When MCP is disabled, an empty catalog ⇒ the PDP default-denies every tool and
        # list_tools is empty — the safe, default-deny posture rather than a hard error.
        catalog = build_catalog() if self._settings.mcp_enabled else ToolCatalog([])
        env = {"local": "dev", "staging": "staging", "prod": "prod"}[self._settings.app_env]
        resolver = McpTargetResolver(catalog=catalog, environment=env)
        pdp = PolicyDecisionPoint(
            registry=catalog.policy_registry(), target_resolver=resolver
        )
        monitor = TrajectoryMonitor()
        # Real ClientSession-backed transport drops in here when mcp_mock_mode is False.
        transport = MockMCPTransport()
        return PdpGuardedMCPConnector(
            catalog=catalog, pdp=pdp, monitor=monitor, transport=transport
        )

    # --- observability (Session 8) ---
    @cached_property
    def observability(self) -> ObservabilityPort:
        raise AdapterNotWired(
            "ObservabilityPort — adapters/observability/phoenix/ (Session 8, build step 11)"
        )

    # --- queue (Session 3+) ---
    @cached_property
    def queue(self) -> QueuePort:
        raise AdapterNotWired("QueuePort — adapters/queue/arq.py (build step: ingestion)")


def build_container(settings: Settings | None = None) -> Container:
    """Construct the application container. Call once at startup; pass via FastAPI state."""
    return Container(settings or get_settings())
