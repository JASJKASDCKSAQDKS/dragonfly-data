"""
Tool set definitions for Jarvis.

Defines which tools belong to which tool set:
- client_tools: Safe, read-only tools for tenant-scoped AI assistant
- developer_tools: Full tool set for developer AI (requires confirmation gate)
"""

from __future__ import annotations

from jarvis.tools.registry import registry

# Client assistant allowlisted tools (read-only, parameterized queries only)
CLIENT_TOOL_NAMES = {
    "get_revenue_kpi",
    "get_profit_kpi",
    "get_top_products",
    "get_bottom_products",
    "get_stock_alerts",
    "get_purchases_vs_sales",
    "get_revenue_chart",
    "get_profit_chart",
    "get_category_breakdown",
    "get_supplier_breakdown",
    "get_product_detail",
}

# Developer tools - all tools including dangerous ones
DEVELOPER_TOOL_NAMES = {
    # Safe tools
    "current_datetime",
    "get_revenue_kpi",
    "get_profit_kpi",
    "get_top_products",
    "get_bottom_products",
    "get_stock_alerts",
    "get_purchases_vs_sales",
    "get_revenue_chart",
    "get_profit_chart",
    "get_category_breakdown",
    "get_supplier_breakdown",
    "get_product_detail",
    # Memory tools
    "remember",
    "recall",
    "forget",
    "list_memories",
    # Filesystem tools
    "read_file",
    "write_file",
    "edit_file",
    "list_directory",
    "find_files",
    # Shell tools
    "run_shell_command",
    # Database tools
    "create_database",
    "generate_database_ui",
    # Self-improvement
    "self_improve",
    # Universal access
    "universal_access",
    # Editor
    "open_file",
    "save_file",
}


def get_tool_set(set_name: str) -> list[dict]:
    """Get Ollama-compatible tool definitions for a tool set."""
    if set_name == "client":
        tool_names = CLIENT_TOOL_NAMES
    elif set_name == "developer":
        tool_names = DEVELOPER_TOOL_NAMES
    else:
        raise ValueError(f"Unknown tool set: {set_name}")

    tools = []
    for name in tool_names:
        defn = registry.get(name)
        if defn:
            tools.append({
                "type": "function",
                "function": {
                    "name": defn.name,
                    "description": defn.description,
                    "parameters": defn.parameters,
                },
            })
        else:
            # Tool not registered (e.g., not imported) - skip silently
            pass
    return tools


def get_client_tools() -> list[dict]:
    """Get client assistant tool definitions."""
    return get_tool_set("client")


def get_developer_tools() -> list[dict]:
    """Get developer assistant tool definitions."""
    return get_tool_set("developer")