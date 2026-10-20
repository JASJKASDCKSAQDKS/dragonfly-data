"""
Analytics API routes (client-scoped).

All endpoints require client authentication and return data only for the
authenticated user's tenant. Tenant is derived from the verified JWT token,
never from client input.

Endpoints:
- GET /api/analytics/kpis/revenue - Revenue KPI
- GET /api/analytics/kpis/profit - Profit KPI
- GET /api/analytics/kpis/top-products - Top products
- GET /api/analytics/kpis/bottom-products - Bottom products
- GET /api/analytics/kpis/stock-alerts - Stock alerts
- GET /api/analytics/kpis/purchases-vs-sales - Purchases vs sales
- GET /api/analytics/charts/revenue - Revenue chart
- GET /api/analytics/charts/profit - Profit chart
- GET /api/analytics/charts/category-breakdown - Category breakdown
- GET /api/analytics/charts/supplier-breakdown - Supplier breakdown
- GET /api/analytics/drilldown/product/{product_id} - Product detail
- GET /api/analytics/drilldown/product/{product_id}/sales - Product sales history
- GET /api/analytics/drilldown/product/{product_id}/purchases - Product purchase history
- GET /api/analytics/snapshot - Complete dashboard snapshot (for offline)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from jarvis.auth.dependencies import require_client, get_current_tenant
from jarvis.auth.models import Tenant, User
from jarvis.analytics.queries import DateRange
from jarvis.analytics.service import get_analytics_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# =========================================================================
# Request/Response Models
# =========================================================================

class DateRangeParams(BaseModel):
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    
    def to_date_range(self) -> DateRange:
        return DateRange.from_strings(self.start_date, self.end_date)


class KPIResponse(BaseModel):
    current: dict
    previous: Optional[dict] = None
    change_pct: Optional[float] = None


class ChartResponse(BaseModel):
    data: list[dict]
    granularity: str


class ProductDetailResponse(BaseModel):
    product: dict
    sales_history: list[dict]
    purchase_history: list[dict]


class SnapshotResponse(BaseModel):
    kpis_revenue: list[dict]
    kpis_profit: list[dict]
    top_products: list[dict]
    bottom_products: list[dict]
    stock_alerts: list[dict]
    purchases_vs_sales: list[dict]
    revenue_chart: list[dict]
    profit_chart: list[dict]
    category_breakdown: list[dict]
    supplier_breakdown: list[dict]


class ExpenseRequest(BaseModel):
    expense_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    description: str = Field(..., min_length=1, max_length=255)
    amount: float = Field(..., gt=0)


# =========================================================================
# Helper Functions
# =========================================================================

def get_date_range(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    days: int = 30,
) -> DateRange:
    """Get date range from query params or default to last N days."""
    if start_date and end_date:
        return DateRange.from_strings(start_date, end_date)
    
    end = date.today()
    start = end - timedelta(days=days)
    return DateRange(start_date=start, end_date=end)


def get_previous_range(current: DateRange) -> DateRange:
    """Get previous period range of same length."""
    delta = current.end_date - current.start_date
    prev_end = current.start_date - timedelta(days=1)
    prev_start = prev_end - delta
    return DateRange(start_date=prev_start, end_date=prev_end)


# =========================================================================
# KPI Endpoints
# =========================================================================

@router.get("/kpis/revenue", response_model=KPIResponse)
async def get_revenue_kpi(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    compare: bool = Query(True, description="Compare with previous period"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get revenue KPI with optional previous period comparison."""
    analytics = get_analytics_service()
    current_range = get_date_range(start_date, end_date)
    previous_range = get_previous_range(current_range) if compare else None
    
    return analytics.get_revenue_kpi(tenant, current_range, previous_range)


@router.get("/kpis/profit", response_model=KPIResponse)
async def get_profit_kpi(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    compare: bool = Query(True, description="Compare with previous period"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get profit KPI with optional previous period comparison."""
    analytics = get_analytics_service()
    current_range = get_date_range(start_date, end_date)
    previous_range = get_previous_range(current_range) if compare else None
    
    return analytics.get_profit_kpi(tenant, current_range, previous_range)


@router.get("/kpis/top-products")
async def get_top_products(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(10, ge=1, le=50),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get top selling products by revenue."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    return analytics.get_top_products(tenant, date_range, limit)


@router.get("/kpis/bottom-products")
async def get_bottom_products(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(10, ge=1, le=50),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get bottom selling products by revenue."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    return analytics.get_bottom_products(tenant, date_range, limit)


@router.get("/kpis/stock-alerts")
async def get_stock_alerts(
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get stock alerts (dead stock)."""
    analytics = get_analytics_service()
    return analytics.get_stock_alerts(tenant)


@router.get("/metadata")
async def get_business_metadata(tenant: Tenant = Depends(get_current_tenant)):
    """Return tenant business/import metadata without exposing database details."""
    analytics = get_analytics_service()
    try:
        result = analytics._execute_query(
            tenant,
            "SELECT business_name, business_type, demo_mode, onboarding_completed, "
            "last_import_id, updated_at FROM business_metadata WHERE metadata_id=1",
            (),
        )
        metadata = result.rows[0] if result.rows else {}
        imports = analytics._execute_query(
            tenant,
            "SELECT imported_at, sync_completed_at, status, rows_imported FROM import_log "
            "ORDER BY imported_at DESC LIMIT 1",
            (),
        )
        return {"business": metadata, "last_import": imports.rows[0] if imports.rows else None}
    except Exception:
        return {"business": {}, "last_import": None}


@router.get("/phase2")
async def get_phase2_dashboard(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Single cached dashboard payload backed by daily/period summary tables."""
    analytics = get_analytics_service()
    current = get_date_range(start_date, end_date)
    previous = get_previous_range(current)
    return {
        "range": {"start_date": current.start_date.isoformat(), "end_date": current.end_date.isoformat()},
        "revenue": analytics.get_revenue_kpi(tenant, current, previous),
        "profit": analytics.get_profit_kpi(tenant, current, previous),
        "revenue_chart": analytics.get_revenue_chart(tenant, current),
        "busy_hours": analytics.get_busy_hours(tenant, current),
        "cash_flow": analytics.get_cash_flow(tenant, current),
        "top_products": analytics.get_top_products(tenant, current, 6),
        "stock_alerts": analytics.get_stock_alerts(tenant),
        "insight": analytics.get_daily_insight(tenant),
    }


@router.get("/cash-expenses")
async def get_cash_expenses(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    date_range = get_date_range(start_date, end_date)
    analytics = get_analytics_service()
    result = analytics._execute_query(
        tenant,
        "SELECT expense_id, expense_date, description, amount FROM cash_expenses "
        "WHERE expense_date BETWEEN %s AND %s ORDER BY expense_date DESC, expense_id DESC LIMIT 100",
        date_range.to_sql_params(),
    )
    return result.rows


@router.get("/weekly-report")
async def weekly_report(tenant: Tenant = Depends(get_current_tenant)):
    """Scheduled delivery is not enabled in the demo build."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Scheduled reports are not enabled in this build",
    )


@router.get("/kpis/purchases-vs-sales")
async def get_purchases_vs_sales(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get purchases vs sales comparison."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    return analytics.get_purchases_vs_sales(tenant, date_range)


# =========================================================================
# Chart Endpoints
# =========================================================================

@router.get("/charts/revenue", response_model=ChartResponse)
async def get_revenue_chart(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    granularity: str = Query("day", pattern=r"^(day|week|month)$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get revenue chart data."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    data = analytics.get_revenue_chart(tenant, date_range, granularity)
    return ChartResponse(data=data, granularity=granularity)


@router.get("/charts/profit", response_model=ChartResponse)
async def get_profit_chart(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    granularity: str = Query("day", pattern=r"^(day|week|month)$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get profit chart data."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    data = analytics.get_profit_chart(tenant, date_range, granularity)
    return ChartResponse(data=data, granularity=granularity)


@router.get("/charts/category-breakdown")
async def get_category_breakdown(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get revenue breakdown by category."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    return analytics.get_category_breakdown(tenant, date_range)


@router.get("/charts/supplier-breakdown")
async def get_supplier_breakdown(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get purchases breakdown by supplier."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    return analytics.get_supplier_breakdown(tenant, date_range)


# =========================================================================
# Drill-down Endpoints
# =========================================================================

@router.get("/drilldown/product/{product_id}", response_model=ProductDetailResponse)
async def get_product_detail(
    product_id: int,
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get detailed performance for a specific product."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    product = analytics.get_product_detail(tenant, product_id, date_range)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    
    sales_history = analytics.get_product_sales_history(tenant, product_id, date_range)
    purchase_history = analytics.get_product_purchase_history(tenant, product_id, date_range)
    
    return ProductDetailResponse(
        product=product,
        sales_history=sales_history,
        purchase_history=purchase_history,
    )


@router.get("/drilldown/product/{product_id}/sales")
async def get_product_sales_history(
    product_id: int,
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(100, ge=1, le=500),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get sales history for a specific product."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    return analytics.get_product_sales_history(tenant, product_id, date_range, limit)


@router.get("/drilldown/product/{product_id}/purchases")
async def get_product_purchase_history(
    product_id: int,
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(100, ge=1, le=500),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get purchase history for a specific product."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    return analytics.get_product_purchase_history(tenant, product_id, date_range, limit)


# =========================================================================
# Snapshot Endpoint (for offline support)
# =========================================================================

@router.get("/snapshot", response_model=SnapshotResponse)
async def get_dashboard_snapshot(
    start_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Get complete dashboard snapshot for offline support."""
    analytics = get_analytics_service()
    date_range = get_date_range(start_date, end_date)
    
    return analytics.get_dashboard_snapshot(tenant, date_range)