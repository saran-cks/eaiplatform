"""MCP transport — the raw, UNGUARDED execution seam.

This is the only place an actual external tool is invoked. It is deliberately dumb: it
performs no authorization (that already happened at the PDP chokepoint upstream). The
``MockMCPTransport`` lets the whole MCP path run with no live MCP servers — mirroring the
Bedrock adapter's mock mode — and the real ``ClientSession``-backed transport drops in
behind the same ``MCPTransportPort`` later (live verification: smoke-tests ST-3).

NOTE: ``call_tool`` here is the raw call. The static chokepoint guard
(``test_pdp_chokepoint.py``) allows the connector to invoke it precisely because the
connector routes through the PDP first; nothing else may.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class MCPTransportPort(Protocol):
    async def call_tool(
        self, *, server: str, name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        ...

    async def close(self) -> None:
        ...


class MockMCPTransport:
    """Returns a canned, echoed payload so the path is exercisable without live servers."""

    async def call_tool(
        self, *, server: str, name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        logger.info("MockMCPTransport invoking %s on %s (args=%s)", name, server, dict(arguments))
        return {
            "server": server,
            "tool": name,
            "arguments": dict(arguments),
            "result": f"[mock result for {name}]",
            "mock": True,
        }

    async def close(self) -> None:
        return None
