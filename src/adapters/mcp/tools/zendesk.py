"""Zendesk read-only MCP tools."""

from __future__ import annotations

from adapters.mcp.tools.base import ToolSpec

SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="zendesk.get_ticket",
        server="zendesk",
        description="Fetch a single Zendesk ticket by id (read-only).",
        target_kind="zendesk:ticket",
        id_arg="ticket_id",
        required_permissions=frozenset({"zendesk:read"}),
        input_schema={
            "type": "object",
            "properties": {"ticket_id": {"type": "string", "description": "Zendesk ticket id"}},
            "required": ["ticket_id"],
        },
    ),
)
