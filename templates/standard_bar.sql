-- Standard Bar Schema Template
-- This template is used when creating new tenant databases
-- Modify this file to customize the schema for all new tenants

-- Products table
CREATE TABLE IF NOT EXISTS products (
  product_id INT AUTO_INCREMENT PRIMARY KEY,
  sku VARCHAR(64) UNIQUE,
  name VARCHAR(150) NOT NULL,
  category VARCHAR(80),
  supplier VARCHAR(120),
  cost_price DECIMAL(10,2) NOT NULL DEFAULT 0,
  sell_price DECIMAL(10,2) NOT NULL DEFAULT 0,
  stock_quantity DECIMAL(10,2) NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Purchases table
CREATE TABLE IF NOT EXISTS purchases (
  purchase_id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  quantity DECIMAL(10,2) NOT NULL,
  unit_cost DECIMAL(10,2) NOT NULL,
  total_cost DECIMAL(10,2) GENERATED ALWAYS AS (quantity * unit_cost) STORED,
  purchase_date DATE NOT NULL,
  invoice_reference VARCHAR(100),
  imported_from VARCHAR(150),
  source_row_key VARCHAR(191),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(product_id),
  KEY idx_purchases_date (purchase_date),
  KEY idx_purchases_product (product_id)
);

-- Sales table
CREATE TABLE IF NOT EXISTS sales (
  sale_id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  quantity DECIMAL(10,2) NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  total_revenue DECIMAL(10,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
  sale_date DATE NOT NULL,
  imported_from VARCHAR(150),
  event_type ENUM('sale','refund','void') NOT NULL DEFAULT 'sale',
  source_row_key VARCHAR(191),
  occurred_at DATETIME NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(product_id),
  KEY idx_sales_date (sale_date),
  KEY idx_sales_product (product_id)
);

-- Import log table
CREATE TABLE IF NOT EXISTS import_log (
  import_id INT AUTO_INCREMENT PRIMARY KEY,
  filename VARCHAR(255),
  import_type ENUM('sales','purchases') NOT NULL,
  rows_imported INT DEFAULT 0,
  rows_skipped INT DEFAULT 0,
  source_system VARCHAR(80),
  source_checksum CHAR(64),
  sync_started_at DATETIME NULL,
  sync_completed_at DATETIME NULL,
  status ENUM('started','completed','failed') NOT NULL DEFAULT 'completed',
  imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

-- MariaDB supports IF NOT EXISTS for indexes; this keeps provisioning repeatable.
CREATE UNIQUE INDEX IF NOT EXISTS uq_purchases_source_row_key ON purchases (source_row_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_source_row_key ON sales (source_row_key);


-- Product performance view
CREATE OR REPLACE VIEW v_product_performance AS
SELECT
  p.product_id, p.name, p.category, p.supplier,
  s.units_sold, s.total_revenue, s.last_sale_date,
  pu.units_purchased, pu.total_spent, pu.last_purchase_date,
  ROUND(COALESCE(s.total_revenue,0) - COALESCE(pu.total_spent,0), 2) AS gross_profit,
  CASE WHEN COALESCE(s.total_revenue,0) > 0
       THEN ROUND((COALESCE(s.total_revenue,0) - COALESCE(pu.total_spent,0)) / s.total_revenue * 100, 1)
       ELSE NULL END AS margin_pct
FROM products p
LEFT JOIN (
  SELECT product_id, SUM(quantity) AS units_sold, SUM(total_revenue) AS total_revenue,
         MAX(sale_date) AS last_sale_date
  FROM sales GROUP BY product_id
) s ON s.product_id = p.product_id
LEFT JOIN (
  SELECT product_id, SUM(quantity) AS units_purchased, SUM(total_cost) AS total_spent,
         MAX(purchase_date) AS last_purchase_date
  FROM purchases GROUP BY product_id
) pu ON pu.product_id = p.product_id;

-- Dead stock view
CREATE OR REPLACE VIEW v_dead_stock AS
SELECT * FROM v_product_performance
WHERE last_purchase_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
  AND (last_sale_date IS NULL OR last_sale_date < DATE_SUB(CURDATE(), INTERVAL 30 DAY))
ORDER BY total_spent DESC;

-- Cash flow contribution view
CREATE OR REPLACE VIEW v_cash_flow_contribution AS
SELECT product_id, name, category, gross_profit, margin_pct, units_sold
FROM v_product_performance
WHERE units_sold IS NOT NULL
ORDER BY gross_profit DESC;

CREATE TABLE IF NOT EXISTS hourly_summary (
  summary_date DATE NOT NULL, weekday TINYINT NOT NULL, hour_of_day TINYINT NOT NULL,
  units_sold DECIMAL(12,2) NOT NULL DEFAULT 0, revenue DECIMAL(12,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (summary_date, hour_of_day)
);
CREATE TABLE IF NOT EXISTS cash_flow_daily (
  summary_date DATE PRIMARY KEY, money_in DECIMAL(12,2) NOT NULL DEFAULT 0,
  money_out DECIMAL(12,2) NOT NULL DEFAULT 0, net DECIMAL(12,2) NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cash_expenses (
  expense_id INT AUTO_INCREMENT PRIMARY KEY, expense_date DATE NOT NULL,
  description VARCHAR(255) NOT NULL, amount DECIMAL(12,2) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ai_daily_insight (
  insight_date DATE PRIMARY KEY, insight_text TEXT NOT NULL,
  generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
