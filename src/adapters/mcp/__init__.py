"""MCP connector adapter package.

The agent's external-action surface (ServiceNow, Confluence, GitHub, Zendesk) reached
over MCP. Every tool call routes through the PDP-guarded ``PdpGuardedMCPConnector`` —
the single, allowlisted chokepoint where DD-8 (action policy) and DD-11 (trajectory risk)
become load-bearing. Tools are read-only in phase 1; writes are FUTURE.
"""
