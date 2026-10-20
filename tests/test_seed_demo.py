from jarvis.seed_demo import build_demo, sql_for_demo
from pathlib import Path


def test_demo_seed_is_deterministic_and_has_expected_shape():
    first = build_demo(seed=11)
    assert first == build_demo(seed=11)
    assert 25 <= len(first["products"]) <= 40
    assert len(first["daily_summary"]) == 90
    assert any(row["event_type"] == "refund" for row in first["sales"])
    assert any(row["event_type"] == "void" for row in first["sales"])
    assert any(row["stock_quantity"] <= 5 for row in first["products"])


def test_demo_sql_is_idempotent_by_keys():
    data = build_demo(seed=3)
    sql = sql_for_demo(data)
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert sql.count("source_row_key") == len(data["sales"]) * 3
    assert "COMMIT;" in sql


def test_phase1_sql_and_dashboard_are_repeatable_and_show_sync_state():
    root = Path(__file__).parents[1]
    schema = (root / "templates" / "standard_bar.sql").read_text()
    migration = (root / "templates" / "migrations" / "001_phase1.sql").read_text()
    dashboard = (root / "static" / "client.js").read_text()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_source_row_key" in schema
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_source_row_key" in migration
    assert "Last synced" in dashboard
    assert "sync_completed_at" in dashboard
    assert "No imports yet" in dashboard
    assert "panel-skeleton" in dashboard
