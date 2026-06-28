"""Confluence read-only MCP tools."""

from __future__ import annotations

from adapters.mcp.tools.base import ToolSpec

SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="confluence.get_page",
        server="confluence",
        description="Fetch a single Confluence page by id (read-only).",
        target_kind="confluence:page",
        id_arg="page_id",
        required_permissions=frozenset({"confluence:read"}),
        input_schema={
            "type": "object",
            "properties": {"page_id": {"type": "string", "description": "Confluence page id"}},
            "required": ["page_id"],
        },
    ),
)
