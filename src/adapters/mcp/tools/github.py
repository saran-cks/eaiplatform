"""GitHub read-only MCP tools."""

from __future__ import annotations

from adapters.mcp.tools.base import ToolSpec

SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="github.get_file",
        server="github",
        description="Fetch the contents of a file at a path in a repo (read-only).",
        target_kind="github:file",
        id_arg="path",
        required_permissions=frozenset({"github:read"}),
        input_schema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/name"},
                "path": {"type": "string", "description": "File path within the repo"},
                "ref": {"type": "string", "description": "Branch/tag/SHA (optional)"},
            },
            "required": ["repo", "path"],
        },
    ),
)
