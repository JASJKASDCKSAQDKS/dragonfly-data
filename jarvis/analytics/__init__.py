"""
Analytics module for Jarvis.

Provides tenant-scoped, read-only API endpoints for KPIs, charts, and drill-downs.
All queries are parameterized and executed with the tenant's read-only database user.
"""

from jarvis.analytics.queries import AnalyticsQueries
from jarvis.analytics.service import AnalyticsService
from jarvis.analytics.routes import router as analytics_router

__all__ = [
    "AnalyticsQueries",
    "AnalyticsService",
    "analytics_router",
]