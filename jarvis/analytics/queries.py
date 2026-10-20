"""
Analytics queries for Jarvis.

Parameterized SQL queries for KPIs, charts, and drill-downs.
All queries are read-only and designed to run against tenant databases
using the read-only database user.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class DateRange:
    """Date range for queries."""
    start_date: date
    end_date: date
    
    @classmethod
    def from_strings(cls, start: str, end: str) -> "DateRange":
        result = cls(
            start_date=datetime.strptime(start, "%Y-%m-%d").date(),
            end_date=datetime.strptime(end, "%Y-%m-%d").date(),
        )
        if result.start_date > result.end_date:
            raise ValueError("start date must be on or before end date")
        return result
    
    def to_sql_params(self) -> tuple:
        return (self.start_date, self.end_date)


class AnalyticsQueries:
    """Collection of parameterized analytics queries."""
    
    # =========================================================================
    # KPI Queries
    # =========================================================================
    
    @staticmethod
    def get_revenue_kpi(date_range: DateRange, previous_range: Optional[DateRange] = None) -> tuple[str, tuple]:
        """Get total revenue for date range with optional previous period comparison."""
        sql = """
            SELECT 
                COALESCE(SUM(net_sales), 0) as revenue,
                COALESCE(SUM(transaction_count), 0) as transaction_count,
                COALESCE(SUM(net_sales) / NULLIF(SUM(transaction_count), 0), 0) as avg_transaction_value
            FROM daily_summary
            WHERE summary_date BETWEEN %s AND %s
        """
        params = date_range.to_sql_params()
        
        if previous_range:
            sql += """
            UNION ALL
            SELECT 
                COALESCE(SUM(net_sales), 0) as revenue,
                COALESCE(SUM(transaction_count), 0) as transaction_count,
                COALESCE(SUM(net_sales) / NULLIF(SUM(transaction_count), 0), 0) as avg_transaction_value
            FROM daily_summary
            WHERE summary_date BETWEEN %s AND %s
            """
            params += previous_range.to_sql_params()
        
        return sql, params
    
    @staticmethod
    def get_profit_kpi(date_range: DateRange, previous_range: Optional[DateRange] = None) -> tuple[str, tuple]:
        """Get gross profit for date range with optional previous period comparison."""
        sql = """
            SELECT 
                COALESCE(SUM(s.total_revenue), 0) - COALESCE(SUM(p.total_cost), 0) as gross_profit,
                CASE 
                    WHEN COALESCE(SUM(s.total_revenue), 0) > 0
                    THEN ROUND((COALESCE(SUM(s.total_revenue), 0) - COALESCE(SUM(p.total_cost), 0)) / SUM(s.total_revenue) * 100, 1)
                    ELSE 0
                END as margin_pct
            FROM sales s
            LEFT JOIN purchases p ON p.product_id = s.product_id 
                AND p.purchase_date BETWEEN %s AND %s
            WHERE s.sale_date BETWEEN %s AND %s
        """
        params = date_range.to_sql_params() + date_range.to_sql_params()
        
        if previous_range:
            sql += """
            UNION ALL
            SELECT 
                COALESCE(SUM(s.total_revenue), 0) - COALESCE(SUM(p.total_cost), 0) as gross_profit,
                CASE 
                    WHEN COALESCE(SUM(s.total_revenue), 0) > 0
                    THEN ROUND((COALESCE(SUM(s.total_revenue), 0) - COALESCE(SUM(p.total_cost), 0)) / SUM(s.total_revenue) * 100, 1)
                    ELSE 0
                END as margin_pct
            FROM sales s
            LEFT JOIN purchases p ON p.product_id = s.product_id 
                AND p.purchase_date BETWEEN %s AND %s
            WHERE s.sale_date BETWEEN %s AND %s
            """
            params += previous_range.to_sql_params() + previous_range.to_sql_params()
        
        return sql, params
    
    @staticmethod
    def get_top_products(date_range: DateRange, limit: int = 10) -> tuple[str, tuple]:
        """Get top selling products by revenue."""
        sql = """
            SELECT 
                p.product_id,
                p.name,
                p.category,
                p.sell_price,
                SUM(s.quantity) as units_sold,
                SUM(s.total_revenue) as total_revenue,
                MAX(s.sale_date) as last_sale_date
            FROM sales s
            JOIN products p ON p.product_id = s.product_id
            WHERE s.sale_date BETWEEN %s AND %s
            GROUP BY p.product_id, p.name, p.category, p.sell_price
            ORDER BY total_revenue DESC
            LIMIT %s
        """
        params = date_range.to_sql_params() + (limit,)
        return sql, params
    
    @staticmethod
    def get_bottom_products(date_range: DateRange, limit: int = 10) -> tuple[str, tuple]:
        """Get bottom selling products by revenue (but with sales > 0)."""
        sql = """
            SELECT 
                p.product_id,
                p.name,
                p.category,
                p.sell_price,
                SUM(s.quantity) as units_sold,
                SUM(s.total_revenue) as total_revenue,
                MAX(s.sale_date) as last_sale_date
            FROM sales s
            JOIN products p ON p.product_id = s.product_id
            WHERE s.sale_date BETWEEN %s AND %s
            GROUP BY p.product_id, p.name, p.category, p.sell_price
            HAVING total_revenue > 0
            ORDER BY total_revenue ASC
            LIMIT %s
        """
        params = date_range.to_sql_params() + (limit,)
        return sql, params
    
    @staticmethod
    def get_stock_alerts() -> tuple[str, tuple]:
        """Get products with low stock (using dead stock view)."""
        sql = """
            SELECT 
                product_id,
                name,
                category,
                units_purchased,
                units_sold,
                total_spent,
                last_purchase_date,
                last_sale_date
            FROM v_dead_stock
            ORDER BY total_spent DESC
            LIMIT 20
        """
        return sql, ()
    
    @staticmethod
    def get_purchases_vs_sales(date_range: DateRange) -> tuple[str, tuple]:
        """Get purchases vs sales comparison."""
        sql = """
            SELECT 
                'sales' as type,
                DATE(sale_date) as period,
                SUM(quantity) as quantity,
                SUM(total_revenue) as value
            FROM sales
            WHERE sale_date BETWEEN %s AND %s
            GROUP BY DATE(sale_date)
            
            UNION ALL
            
            SELECT 
                'purchases' as type,
                DATE(purchase_date) as period,
                SUM(quantity) as quantity,
                SUM(total_cost) as value
            FROM purchases
            WHERE purchase_date BETWEEN %s AND %s
            GROUP BY DATE(purchase_date)
            
            ORDER BY period, type
        """
        params = date_range.to_sql_params() + date_range.to_sql_params()
        return sql, params
    
    # =========================================================================
    # Chart Queries
    # =========================================================================
    
    @staticmethod
    def get_revenue_chart(date_range: DateRange, granularity: str = "day") -> tuple[str, tuple]:
        """Get revenue chart data grouped by day/week/month."""
        group_by = {
            "day": "DATE(summary_date)",
            "week": "YEARWEEK(summary_date, 1)",
            "month": "DATE_FORMAT(summary_date, '%%Y-%%m')",
        }.get(granularity, "DATE(summary_date)")
        
        select_fmt = {
            "day": "DATE(sale_date) as period",
            "week": "CONCAT(YEAR(sale_date), '-W', LPAD(WEEK(sale_date, 1), 2, '0')) as period",
            "month": "DATE_FORMAT(sale_date, '%%Y-%%m') as period",
        }.get(granularity, "DATE(sale_date) as period")
        
        sql = f"""
            SELECT 
                {select_fmt.replace("sale_date", "summary_date")},
                SUM(net_sales) as revenue,
                SUM(transaction_count) as transactions
            FROM daily_summary
            WHERE summary_date BETWEEN %s AND %s
            GROUP BY {group_by}
            ORDER BY period
        """
        params = date_range.to_sql_params()
        return sql, params
    
    @staticmethod
    def get_profit_chart(date_range: DateRange, granularity: str = "day") -> tuple[str, tuple]:
        """Get profit chart data grouped by day/week/month."""
        group_by = {
            "day": "DATE(s.sale_date)",
            "week": "YEARWEEK(s.sale_date, 1)",
            "month": "DATE_FORMAT(s.sale_date, '%%Y-%%m')",
        }.get(granularity, "DATE(s.sale_date)")
        
        select_fmt = {
            "day": "DATE(s.sale_date) as period",
            "week": "CONCAT(YEAR(s.sale_date), '-W', LPAD(WEEK(s.sale_date, 1), 2, '0')) as period",
            "month": "DATE_FORMAT(s.sale_date, '%%Y-%%m') as period",
        }.get(granularity, "DATE(s.sale_date) as period")
        
        sql = f"""
            SELECT 
                {select_fmt},
                COALESCE(SUM(s.total_revenue), 0) - COALESCE(SUM(p.total_cost), 0) as gross_profit,
                CASE 
                    WHEN COALESCE(SUM(s.total_revenue), 0) > 0
                    THEN ROUND((COALESCE(SUM(s.total_revenue), 0) - COALESCE(SUM(p.total_cost), 0)) / SUM(s.total_revenue) * 100, 1)
                    ELSE 0
                END as margin_pct
            FROM sales s
            LEFT JOIN purchases p ON p.product_id = s.product_id 
                AND p.purchase_date BETWEEN %s AND %s
            WHERE s.sale_date BETWEEN %s AND %s
            GROUP BY {group_by}
            ORDER BY period
        """
        params = date_range.to_sql_params() + date_range.to_sql_params()
        return sql, params
    
    @staticmethod
    def get_category_breakdown(date_range: DateRange) -> tuple[str, tuple]:
        """Get revenue breakdown by category."""
        sql = """
            SELECT 
                p.category,
                SUM(s.total_revenue) as revenue,
                SUM(s.quantity) as units_sold,
                COUNT(DISTINCT s.sale_id) as transactions
            FROM sales s
            JOIN products p ON p.product_id = s.product_id
            WHERE s.sale_date BETWEEN %s AND %s
            GROUP BY p.category
            ORDER BY revenue DESC
        """
        params = date_range.to_sql_params()
        return sql, params
    
    @staticmethod
    def get_supplier_breakdown(date_range: DateRange) -> tuple[str, tuple]:
        """Get purchases breakdown by supplier."""
        sql = """
            SELECT 
                p.supplier,
                SUM(pu.total_cost) as total_spent,
                SUM(pu.quantity) as units_purchased,
                COUNT(DISTINCT pu.purchase_id) as orders
            FROM purchases pu
            JOIN products p ON p.product_id = pu.product_id
            WHERE pu.purchase_date BETWEEN %s AND %s
            GROUP BY p.supplier
            ORDER BY total_spent DESC
        """
        params = date_range.to_sql_params()
        return sql, params
    
    # =========================================================================
    # Drill-down Queries
    # =========================================================================
    
    @staticmethod
    def get_product_detail(product_id: int, date_range: DateRange) -> tuple[str, tuple]:
        """Get detailed performance for a specific product."""
        sql = """
            SELECT 
                p.product_id,
                p.name,
                p.category,
                p.supplier,
                p.cost_price,
                p.sell_price,
                COALESCE(SUM(s.quantity), 0) as units_sold,
                COALESCE(SUM(s.total_revenue), 0) as total_revenue,
                COALESCE(SUM(pu.quantity), 0) as units_purchased,
                COALESCE(SUM(pu.total_cost), 0) as total_cost,
                MAX(s.sale_date) as last_sale_date,
                MAX(pu.purchase_date) as last_purchase_date
            FROM products p
            LEFT JOIN sales s ON s.product_id = p.product_id 
                AND s.sale_date BETWEEN %s AND %s
            LEFT JOIN purchases pu ON pu.product_id = p.product_id 
                AND pu.purchase_date BETWEEN %s AND %s
            WHERE p.product_id = %s
            GROUP BY p.product_id, p.name, p.category, p.supplier, p.cost_price, p.sell_price
        """
        params = date_range.to_sql_params() + date_range.to_sql_params() + (product_id,)
        return sql, params
    
    @staticmethod
    def get_product_sales_history(product_id: int, date_range: DateRange, limit: int = 100) -> tuple[str, tuple]:
        """Get sales history for a specific product."""
        sql = """
            SELECT 
                sale_id,
                sale_date,
                quantity,
                unit_price,
                total_revenue
            FROM sales
            WHERE product_id = %s AND sale_date BETWEEN %s AND %s
            ORDER BY sale_date DESC
            LIMIT %s
        """
        params = (product_id,) + date_range.to_sql_params() + (limit,)
        return sql, params
    
    @staticmethod
    def get_product_purchase_history(product_id: int, date_range: DateRange, limit: int = 100) -> tuple[str, tuple]:
        """Get purchase history for a specific product."""
        sql = """
            SELECT 
                purchase_id,
                purchase_date,
                quantity,
                unit_cost,
                total_cost,
                invoice_reference
            FROM purchases
            WHERE product_id = %s AND purchase_date BETWEEN %s AND %s
            ORDER BY purchase_date DESC
            LIMIT %s
        """
        params = (product_id,) + date_range.to_sql_params() + (limit,)
        return sql, params
    
    # =========================================================================
    # Snapshot Query (for offline support)
    # =========================================================================
    
    @staticmethod
    def get_dashboard_snapshot(date_range: DateRange) -> list[tuple[str, tuple]]:
        """Get all queries needed for a complete dashboard snapshot."""
        return [
            ("kpis_revenue", AnalyticsQueries.get_revenue_kpi(date_range)),
            ("kpis_profit", AnalyticsQueries.get_profit_kpi(date_range)),
            ("top_products", AnalyticsQueries.get_top_products(date_range, 10)),
            ("bottom_products", AnalyticsQueries.get_bottom_products(date_range, 10)),
            ("stock_alerts", AnalyticsQueries.get_stock_alerts()),
            ("purchases_vs_sales", AnalyticsQueries.get_purchases_vs_sales(date_range)),
            ("revenue_chart", AnalyticsQueries.get_revenue_chart(date_range, "day")),
            ("profit_chart", AnalyticsQueries.get_profit_chart(date_range, "day")),
            ("category_breakdown", AnalyticsQueries.get_category_breakdown(date_range)),
            ("supplier_breakdown", AnalyticsQueries.get_supplier_breakdown(date_range)),
        ]

    @staticmethod
    def get_busy_hours(date_range: DateRange) -> tuple[str, tuple]:
        """Read precomputed weekday/hour aggregates (never scan sales on dashboard load)."""
        return ("""SELECT weekday, hour_of_day, units_sold, revenue
                    FROM hourly_summary
                    WHERE summary_date BETWEEN %s AND %s
                    ORDER BY weekday, hour_of_day""", date_range.to_sql_params())

    @staticmethod
    def get_cash_flow(date_range: DateRange) -> tuple[str, tuple]:
        return ("""SELECT summary_date, money_in, money_out, net
                    FROM cash_flow_daily
                    WHERE summary_date BETWEEN %s AND %s
                    ORDER BY summary_date""", date_range.to_sql_params())

    @staticmethod
    def get_insight() -> tuple[str, tuple]:
        return ("SELECT insight_date, insight_text FROM ai_daily_insight "
                "WHERE insight_date = CURDATE() LIMIT 1", ())