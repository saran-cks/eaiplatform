"""Read-only MCP tool specifications, one module per source system.

Each ``ToolSpec`` declares both its *display* surface (for ``list_tools``) and its
*policy* surface (``to_policy()`` → the per-tool ``ToolPolicy`` the PDP enforces). A tool
with no spec has no policy and is therefore default-denied by the PDP.
"""
