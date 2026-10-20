"""
Client Assistant Tools for Jarvis.

Allowlisted read-only tools that the client AI can use to answer questions
about their business data. No shell, no filesystem, no free-form SQL,
no self-modification - only parameterized, read-only queries.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, Optional

from jarvis.tools.registry import tool
from jarvis.analytics.service import get_analytics_service
from jarvis.tenants.service import get_tenant_service
from jarvis.tenants.models import Tenant

log = logging.getLogger(__name__)


class ClientAssistantTools:
    """Allowlisted tools for client AI assistant."""
    
    def __init__(self, tenant: Tenant):
        self.tenant = tenant
        self.analytics = get_analytics_service()
    
    def get_tool_definitions(self) -> list[dict]:
        """Get Ollama-compatible tool definitions for the allowlisted tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_revenue_kpi",
                    "description": "Get revenue KPI for a date range with optional previous period comparison",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                            "compare": {"type": "boolean", "description": "Compare with previous period", "default": True},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_profit_kpi",
                    "description": "Get profit/margin KPI for a date range with optional previous period comparison",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                            "compare": {"type": "boolean", "description": "Compare with previous period", "default": True},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_products",
                    "description": "Get top selling products by revenue",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                            "limit": {"type": "integer", "description": "Number of products to return", "default": 10},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_bottom_products",
                    "description": "Get bottom selling products by revenue",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                            "limit": {"type": "integer", "description": "Number of products to return", "default": 10},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stock_alerts",
                    "description": "Get stock alerts (dead stock, slow movers)",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_purchases_vs_sales",
                    "description": "Get purchases vs sales comparison over time",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_revenue_chart",
                    "description": "Get revenue chart data grouped by day/week/month",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                            "granularity": {"type": "string", "enum": ["day", "week", "month"], "default": "day"},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_profit_chart",
                    "description": "Get profit chart data grouped by day/week/month",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                            "granularity": {"type": "string", "enum": ["day", "week", "month"], "default": "day"},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_category_breakdown",
                    "description": "Get revenue breakdown by product category",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_supplier_breakdown",
                    "description": "Get purchases breakdown by supplier",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                        },
                        "required": ["start_date", "end_date"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_product_detail",
                    "description": "Get detailed performance for a specific product",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "integer", "description": "Product ID"},
                            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                            "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                        },
                        "required": ["product_id", "start_date", "end_date"],
                    },
                },
            },
        ]
    
    # =========================================================================
    # Tool Implementations
    # =========================================================================
    
    async def get_revenue_kpi(self, start_date: str, end_date: str, compare: bool = True) -> str:
        """Get revenue KPI."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        previous_range = None
        if compare:
            delta = date_range.end_date - date_range.start_date
            prev_end = date_range.start_date - timedelta(days=1)
            prev_start = prev_end - delta
            previous_range = DateRange(start_date=prev_start, end_date=prev_end)
        
        result = self.analytics.get_revenue_kpi(self.tenant, date_range, previous_range)
        return json.dumps(result, default=str)
    
    async def get_profit_kpi(self, start_date: str, end_date: str, compare: bool = True) -> str:
        """Get profit KPI."""
        from jarvis.analytics.queries import DateRange
        from datetime import timedelta
        date_range = DateRange.from_strings(start_date, end_date)
        previous_range = None
        if compare:
            delta = date_range.end_date - date_range.start_date
            prev_end = date_range.start_date - timedelta(days=1)
            prev_start = prev_end - delta
            previous_range = DateRange(start_date=prev_start, end_date=prev_end)
        
        result = self.analytics.get_profit_kpi(self.tenant, date_range, previous_range)
        return json.dumps(result, default=str)
    
    async def get_top_products(self, start_date: str, end_date: str, limit: int = 10) -> str:
        """Get top selling products."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        result = self.analytics.get_top_products(self.tenant, date_range, limit)
        return json.dumps(result, default=str)
    
    async def get_bottom_products(self, start_date: str, end_date: str, limit: int = 10) -> str:
        """Get bottom selling products."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        result = self.analytics.get_bottom_products(self.tenant, date_range, limit)
        return json.dumps(result, default=str)
    
    async def get_stock_alerts(self) -> str:
        """Get stock alerts."""
        result = self.analytics.get_stock_alerts(self.tenant)
        return json.dumps(result, default=str)
    
    async def get_purchases_vs_sales(self, start_date: str, end_date: str) -> str:
        """Get purchases vs sales comparison."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        result = self.analytics.get_purchases_vs_sales(self.tenant, date_range)
        return json.dumps(result, default=str)
    
    async def get_revenue_chart(self, start_date: str, end_date: str, granularity: str = "day") -> str:
        """Get revenue chart data."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        result = self.analytics.get_revenue_chart(self.tenant, date_range, granularity)
        return json.dumps(result, default=str)
    
    async def get_profit_chart(self, start_date: str, end_date: str, granularity: str = "day") -> str:
        """Get profit chart data."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        result = self.analytics.get_profit_chart(self.tenant, date_range, granularity)
        return json.dumps(result, default=str)
    
    async def get_category_breakdown(self, start_date: str, end_date: str) -> str:
        """Get category breakdown."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        result = self.analytics.get_category_breakdown(self.tenant, date_range)
        return json.dumps(result, default=str)
    
    async def get_supplier_breakdown(self, start_date: str, end_date: str) -> str:
        """Get supplier breakdown."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        result = self.analytics.get_supplier_breakdown(self.tenant, date_range)
        return json.dumps(result, default=str)
    
    async def get_product_detail(self, product_id: int, start_date: str, end_date: str) -> str:
        """Get product detail."""
        from jarvis.analytics.queries import DateRange
        date_range = DateRange.from_strings(start_date, end_date)
        result = self.analytics.get_product_detail(self.tenant, product_id, date_range)
        if not result:
            return json.dumps({"error": "Product not found"})
        return json.dumps(result, default=str)


# Register tools with the global registry for the client assistant
# These are registered dynamically per-tenant in the assistant service
def register_client_tools(tenant: Tenant) -> ClientAssistantTools:
    """Create and return a ClientAssistantTools instance for a tenant."""
    return ClientAssistantTools(tenant)