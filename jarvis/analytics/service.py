"""
Analytics service for Jarvis.

Executes tenant-scoped analytics queries using the read-only database user.
Provides caching and connection management.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

import mysql.connector
from mysql.connector import Error as MySQLError

from jarvis import config
from jarvis.analytics.queries import AnalyticsQueries, DateRange
from jarvis.tenants.service import get_tenant_service
from jarvis.tenants.models import Tenant

log = logging.getLogger(__name__)


@dataclass
class QueryResult:
    """Result of a query execution."""
    columns: list[str]
    rows: list[dict]
    execution_time_ms: float


class AnalyticsService:
    """Service for executing tenant-scoped analytics queries."""
    
    def __init__(self):
        self._cache: dict[str, tuple[Any, float]] = {}  # key -> (result, timestamp)
        self._cache_ttl = 300  # 5 minutes default
    
    def _get_tenant_connection(self, tenant: Tenant):
        """Get read-only connection to tenant's database."""
        return mysql.connector.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=tenant.db_user,
            password=tenant.db_password,
            database=tenant.db_name,
            connection_timeout=5,
        )
    
    def _execute_query(self, tenant: Tenant, sql: str, params: tuple) -> QueryResult:
        """Execute a query against tenant's database."""
        start_time = time.time()
        
        conn = self._get_tenant_connection(tenant)
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            columns = [col[0] for col in cursor.description] if cursor.description else []
            cursor.close()
            conn.close()
            
            execution_time = (time.time() - start_time) * 1000
            return QueryResult(columns=columns, rows=rows, execution_time_ms=execution_time)
        except MySQLError as e:
            conn.close()
            log.error(f"Query failed for tenant {tenant.name}: {e}")
            raise

    def _execute_write(self, tenant: Tenant, sql: str, params: tuple) -> None:
        conn = self._get_tenant_connection(tenant)
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            cursor.close()
        finally:
            conn.close()

    def add_cash_expense(self, tenant: Tenant, expense_date: date, description: str, amount: float) -> None:
        self._execute_write(
            tenant,
            "INSERT INTO cash_expenses (expense_date, description, amount) VALUES (%s, %s, %s)",
            (expense_date, description, amount),
        )
        self.clear_cache(tenant.id)
    
    def _cache_key(self, tenant_id: int, query_name: str, params: tuple) -> str:
        """Generate cache key."""
        import hashlib
        param_str = str(params)
        return f"{tenant_id}:{query_name}:{hashlib.md5(param_str.encode()).hexdigest()}"
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached result if not expired."""
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return result
            else:
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, result: Any):
        """Cache result with timestamp."""
        self._cache[key] = (result, time.time())
    
    def set_cache_ttl(self, ttl_seconds: int):
        """Set cache TTL."""
        self._cache_ttl = ttl_seconds
    
    def clear_cache(self, tenant_id: Optional[int] = None):
        """Clear cache for specific tenant or all."""
        if tenant_id is None:
            self._cache.clear()
        else:
            keys_to_delete = [k for k in self._cache if k.startswith(f"{tenant_id}:")]
            for k in keys_to_delete:
                del self._cache[k]
    
    # =========================================================================
    # KPI Methods
    # =========================================================================
    
    def get_revenue_kpi(self, tenant: Tenant, date_range: DateRange, 
                        previous_range: Optional[DateRange] = None) -> dict:
        """Get revenue KPI with optional previous period comparison."""
        key = self._cache_key(tenant.id, "revenue", (date_range, previous_range))
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        sql, params = AnalyticsQueries.get_revenue_kpi(date_range, previous_range)
        result = self._execute_query(tenant, sql, params)
        
        current = result.rows[0] if result.rows else {"revenue": 0, "transaction_count": 0, "avg_transaction_value": 0}
        
        response = {
            "current": current,
            "previous": None,
            "change_pct": None,
        }
        
        if previous_range and len(result.rows) > 1:
            previous = result.rows[1]
            response["previous"] = previous
            if previous["revenue"] > 0:
                response["change_pct"] = round(
                    (current["revenue"] - previous["revenue"]) / previous["revenue"] * 100, 1
                )
        
        self._set_cache(key, response)
        return response
    
    def get_profit_kpi(self, tenant: Tenant, date_range: DateRange,
                       previous_range: Optional[DateRange] = None) -> dict:
        """Get profit KPI with optional previous period comparison."""
        sql, params = AnalyticsQueries.get_profit_kpi(date_range, previous_range)
        result = self._execute_query(tenant, sql, params)
        
        current = result.rows[0] if result.rows else {"gross_profit": 0, "margin_pct": 0}
        
        response = {
            "current": current,
            "previous": None,
            "change_pct": None,
        }
        
        if previous_range and len(result.rows) > 1:
            previous = result.rows[1]
            response["previous"] = previous
            if previous["gross_profit"] != 0:
                response["change_pct"] = round(
                    (current["gross_profit"] - previous["gross_profit"]) / abs(previous["gross_profit"]) * 100, 1
                )
        
        return response
    
    def get_top_products(self, tenant: Tenant, date_range: DateRange, limit: int = 10) -> list[dict]:
        """Get top selling products."""
        sql, params = AnalyticsQueries.get_top_products(date_range, limit)
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    def get_bottom_products(self, tenant: Tenant, date_range: DateRange, limit: int = 10) -> list[dict]:
        """Get bottom selling products."""
        sql, params = AnalyticsQueries.get_bottom_products(date_range, limit)
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    def get_stock_alerts(self, tenant: Tenant) -> list[dict]:
        """Get stock alerts (dead stock)."""
        sql, params = AnalyticsQueries.get_stock_alerts()
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    def get_purchases_vs_sales(self, tenant: Tenant, date_range: DateRange) -> list[dict]:
        """Get purchases vs sales comparison."""
        sql, params = AnalyticsQueries.get_purchases_vs_sales(date_range)
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    # =========================================================================
    # Chart Methods
    # =========================================================================
    
    def get_revenue_chart(self, tenant: Tenant, date_range: DateRange, 
                          granularity: str = "day") -> list[dict]:
        """Get revenue chart data."""
        key = self._cache_key(tenant.id, "revenue-chart", (date_range, granularity))
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        sql, params = AnalyticsQueries.get_revenue_chart(date_range, granularity)
        result = self._execute_query(tenant, sql, params)
        self._set_cache(key, result.rows)
        return result.rows

    def get_busy_hours(self, tenant: Tenant, date_range: DateRange) -> list[dict]:
        key = self._cache_key(tenant.id, "busy-hours", (date_range,))
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        sql, params = AnalyticsQueries.get_busy_hours(date_range)
        rows = self._execute_query(tenant, sql, params).rows
        self._set_cache(key, rows)
        return rows

    def get_cash_flow(self, tenant: Tenant, date_range: DateRange) -> list[dict]:
        key = self._cache_key(tenant.id, "cash-flow", (date_range,))
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        sql, params = AnalyticsQueries.get_cash_flow(date_range)
        rows = self._execute_query(tenant, sql, params).rows
        self._set_cache(key, rows)
        return rows

    def get_daily_insight(self, tenant: Tenant) -> Optional[dict]:
        sql, params = AnalyticsQueries.get_insight()
        rows = self._execute_query(tenant, sql, params).rows
        return rows[0] if rows else None
    
    def get_profit_chart(self, tenant: Tenant, date_range: DateRange,
                         granularity: str = "day") -> list[dict]:
        """Get profit chart data."""
        sql, params = AnalyticsQueries.get_profit_chart(date_range, granularity)
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    def get_category_breakdown(self, tenant: Tenant, date_range: DateRange) -> list[dict]:
        """Get revenue breakdown by category."""
        sql, params = AnalyticsQueries.get_category_breakdown(date_range)
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    def get_supplier_breakdown(self, tenant: Tenant, date_range: DateRange) -> list[dict]:
        """Get purchases breakdown by supplier."""
        sql, params = AnalyticsQueries.get_supplier_breakdown(date_range)
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    # =========================================================================
    # Drill-down Methods
    # =========================================================================
    
    def get_product_detail(self, tenant: Tenant, product_id: int, 
                           date_range: DateRange) -> Optional[dict]:
        """Get detailed performance for a specific product."""
        sql, params = AnalyticsQueries.get_product_detail(product_id, date_range)
        result = self._execute_query(tenant, sql, params)
        return result.rows[0] if result.rows else None
    
    def get_product_sales_history(self, tenant: Tenant, product_id: int,
                                  date_range: DateRange, limit: int = 100) -> list[dict]:
        """Get sales history for a specific product."""
        sql, params = AnalyticsQueries.get_product_sales_history(product_id, date_range, limit)
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    def get_product_purchase_history(self, tenant: Tenant, product_id: int,
                                     date_range: DateRange, limit: int = 100) -> list[dict]:
        """Get purchase history for a specific product."""
        sql, params = AnalyticsQueries.get_product_purchase_history(product_id, date_range, limit)
        result = self._execute_query(tenant, sql, params)
        return result.rows
    
    # =========================================================================
    # Snapshot Method (for offline support)
    # =========================================================================
    
    def get_dashboard_snapshot(self, tenant: Tenant, date_range: DateRange) -> dict:
        """Get complete dashboard snapshot for offline support."""
        snapshot = {}
        
        queries = AnalyticsQueries.get_dashboard_snapshot(date_range)
        for name, (sql, params) in queries:
            try:
                result = self._execute_query(tenant, sql, params)
                snapshot[name] = result.rows
            except Exception as e:
                log.error(f"Snapshot query {name} failed: {e}")
                snapshot[name] = []
        
        return snapshot


# Global singleton
_analytics_service: Optional[AnalyticsService] = None


def get_analytics_service() -> AnalyticsService:
    """Get the global AnalyticsService singleton."""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AnalyticsService()
    return _analytics_service