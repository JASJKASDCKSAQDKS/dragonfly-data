-- Additive Phase 1 migration. Safe to run repeatedly on every tenant database.
CREATE TABLE IF NOT EXISTS schema_migrations (
  version VARCHAR(64) PRIMARY KEY,
  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_quantity DECIMAL(10,2) NOT NULL DEFAULT 0;
ALTER TABLE purchases ADD COLUMN IF NOT EXISTS source_row_key VARCHAR(191);
ALTER TABLE sales ADD COLUMN IF NOT EXISTS event_type ENUM('sale','refund','void') NOT NULL DEFAULT 'sale';
ALTER TABLE sales ADD COLUMN IF NOT EXISTS source_row_key VARCHAR(191);
ALTER TABLE sales ADD COLUMN IF NOT EXISTS occurred_at DATETIME NULL;
ALTER TABLE import_log ADD COLUMN IF NOT EXISTS source_system VARCHAR(80);
ALTER TABLE import_log ADD COLUMN IF NOT EXISTS source_checksum CHAR(64);
ALTER TABLE import_log ADD COLUMN IF NOT EXISTS sync_started_at DATETIME NULL;
ALTER TABLE import_log ADD COLUMN IF NOT EXISTS sync_completed_at DATETIME NULL;
ALTER TABLE import_log ADD COLUMN IF NOT EXISTS status ENUM('started','completed','failed') NOT NULL DEFAULT 'completed';

CREATE TABLE IF NOT EXISTS business_metadata (
  metadata_id TINYINT PRIMARY KEY,
  business_name VARCHAR(150) NOT NULL,
  business_type VARCHAR(80) NOT NULL DEFAULT 'bar',
  demo_mode TINYINT(1) NOT NULL DEFAULT 0,
  currency CHAR(3) NOT NULL DEFAULT 'EUR',
  onboarding_completed TINYINT(1) NOT NULL DEFAULT 0,
  last_import_id INT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS daily_summary (
  summary_date DATE PRIMARY KEY,
  transaction_count INT NOT NULL DEFAULT 0,
  gross_sales DECIMAL(12,2) NOT NULL DEFAULT 0,
  refunds DECIMAL(12,2) NOT NULL DEFAULT 0,
  voids DECIMAL(12,2) NOT NULL DEFAULT 0,
  net_sales DECIMAL(12,2) NOT NULL DEFAULT 0,
  units_sold DECIMAL(12,2) NOT NULL DEFAULT 0,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_purchases_source_row_key ON purchases (source_row_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_source_row_key ON sales (source_row_key);
INSERT IGNORE INTO schema_migrations(version) VALUES ('001_phase1');

-- Phase 2 precomputed aggregates and owner-entered cash expenses.
CREATE TABLE IF NOT EXISTS hourly_summary (
  summary_date DATE NOT NULL,
  weekday TINYINT NOT NULL,
  hour_of_day TINYINT NOT NULL,
  units_sold DECIMAL(12,2) NOT NULL DEFAULT 0,
  revenue DECIMAL(12,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (summary_date, hour_of_day)
);
CREATE TABLE IF NOT EXISTS cash_flow_daily (
  summary_date DATE PRIMARY KEY,
  money_in DECIMAL(12,2) NOT NULL DEFAULT 0,
  money_out DECIMAL(12,2) NOT NULL DEFAULT 0,
  net DECIMAL(12,2) NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cash_expenses (
  expense_id INT AUTO_INCREMENT PRIMARY KEY,
  expense_date DATE NOT NULL,
  description VARCHAR(255) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_cash_expenses_date (expense_date)
);
CREATE TABLE IF NOT EXISTS ai_daily_insight (
  insight_date DATE PRIMARY KEY,
  insight_text TEXT NOT NULL,
  generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
INSERT IGNORE INTO schema_migrations(version) VALUES ('002_phase2');
