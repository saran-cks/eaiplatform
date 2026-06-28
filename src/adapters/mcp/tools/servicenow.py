"""ServiceNow read-only MCP tools."""

from __future__ import annotations

from adapters.mcp.tools.base import ToolSpec

SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="servicenow.get_incident",
        server="servicenow",
        description="Fetch a single ServiceNow incident by its number (read-only).",
        target_kind="servicenow:incident",
        id_arg="number",
        required_permissions=frozenset({"servicenow:read"}),
        input_schema={
            "type": "object",
            "properties": {"number": {"type": "string", "description": "Incident number"}},
            "required": ["number"],
        },
    ),
)
