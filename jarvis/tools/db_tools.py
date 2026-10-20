"""
Database creation tools — Jarvis can create new MariaDB databases and
register them so the Seline Databases panel renders an admin interface
for them automatically (browse / add / edit / delete rows, per schema).

``create_database`` needs the privileged ``seline_admin`` MySQL user
(created once via setup_admin_user.sh). Without it the
tool returns setup instructions instead of failing cryptically.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

from jarvis import config
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

# Use config settings instead of hardcoded paths. The AI-created-database
# registry is separate from the tenant registry (different file shapes).
_ENV_PATH = str(config.PROJECT_ROOT / ".env")
_REGISTRY_PATH = config.DB_REGISTRY_PATH
_TEMPLATE_PATH = config.TENANT_DB_TEMPLATE

_IDENT_FIX = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_COL_TYPE = re.compile(
    r"^(INT|BIGINT|TINYINT|TINYINT\(1\)|DECIMAL\(10,2\)|"
    r"VARCHAR\(\d{1,3}\)|TEXT|DATE|DATETIME|TIMESTAMP)$",
    re.IGNORECASE,
)

_ADMIN_HELP = (
    "Database creation is locked until the privileged MySQL user exists. "
    "Set ADMIN_DB_USER and ADMIN_DB_PASSWORD in .env "
    "— then ask me again."
)


def _slugify(text: str) -> str:
    """Turn a spoken name into a valid database name: "Mike's Bar" -> mikes_bar."""
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    if not slug:
        return ""
    if slug[0].isdigit():
        slug = "bar_" + slug
    return slug[:63]


def _load_template_statements() -> list[str] | None:
    """Load the standard template SQL file (user-editable) as a statement list.

    Returns None if the file is missing — caller falls back to the embedded
    default schema.
    """
    try:
        with open(_TEMPLATE_PATH) as f:
            text = f.read()
    except FileNotFoundError:
        return None
    statements = []
    for chunk in text.split(";\n"):
        lines = [ln for ln in chunk.splitlines() if ln.strip() and not ln.strip().startswith("--")]
        if lines:
            statements.append("\n".join(lines))
    return statements or None


# Standard bar template (same schema as database-bar1/init/*.sql) — used when
# the user asks for a new bar database without specifying tables.
DEFAULT_BAR_SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS products (
  product_id INT AUTO_INCREMENT PRIMARY KEY,
  sku VARCHAR(64) UNIQUE,
  name VARCHAR(150) NOT NULL,
  category VARCHAR(80),
  supplier VARCHAR(120),
  cost_price DECIMAL(10,2) NOT NULL DEFAULT 0,
  sell_price DECIMAL(10,2) NOT NULL DEFAULT 0,
  active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
    """CREATE TABLE IF NOT EXISTS purchases (
  purchase_id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  quantity DECIMAL(10,2) NOT NULL,
  unit_cost DECIMAL(10,2) NOT NULL,
  total_cost DECIMAL(10,2) GENERATED ALWAYS AS (quantity * unit_cost) STORED,
  purchase_date DATE NOT NULL,
  invoice_reference VARCHAR(100),
  imported_from VARCHAR(150),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(product_id),
  KEY idx_purchases_date (purchase_date),
  KEY idx_purchases_product (product_id)
)""",
    """CREATE TABLE IF NOT EXISTS sales (
  sale_id INT AUTO_INCREMENT PRIMARY KEY,
  product_id INT NOT NULL,
  quantity DECIMAL(10,2) NOT NULL,
  unit_price DECIMAL(10,2) NOT NULL,
  total_revenue DECIMAL(10,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
  sale_date DATE NOT NULL,
  imported_from VARCHAR(150),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(product_id),
  KEY idx_sales_date (sale_date),
  KEY idx_sales_product (product_id)
)""",
    """CREATE TABLE IF NOT EXISTS import_log (
  import_id INT AUTO_INCREMENT PRIMARY KEY,
  filename VARCHAR(255),
  import_type ENUM('sales','purchases') NOT NULL,
  rows_imported INT DEFAULT 0,
  rows_skipped INT DEFAULT 0,
  imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)""",
]

DEFAULT_BAR_VIEWS_SQL = [
    """CREATE OR REPLACE VIEW v_product_performance AS
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
) pu ON pu.product_id = p.product_id""",
    """CREATE OR REPLACE VIEW v_dead_stock AS
SELECT * FROM v_product_performance
WHERE last_purchase_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
  AND (last_sale_date IS NULL OR last_sale_date < DATE_SUB(CURDATE(), INTERVAL 30 DAY))
ORDER BY total_spent DESC""",
    """CREATE OR REPLACE VIEW v_cash_flow_contribution AS
SELECT product_id, name, category, gross_profit, margin_pct, units_sold
FROM v_product_performance
WHERE units_sold IS NOT NULL
ORDER BY gross_profit DESC""",
]


# ---------------------------------------------------------------------------
# Env + registry helpers (shared shape with jarvis/web/dbadmin.py)
# ---------------------------------------------------------------------------

def _load_env() -> dict:
    values: dict[str, str] = {}
    try:
        with open(_ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    values[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return values


def _admin_creds() -> tuple[str, str] | None:
    # Use config values directly (set from .env)
    user = config.ADMIN_DB_USER
    password = config.ADMIN_DB_PASSWORD
    if user and password:
        return user, password
    return None


def _load_registry() -> list[dict]:
    try:
        with open(_REGISTRY_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_registry(entries: list[dict]) -> None:
    tmp = _REGISTRY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, _REGISTRY_PATH)


def _registry_entry(name: str) -> dict | None:
    for e in _load_registry():
        if e.get("name") == name:
            return e
    return None


def _provision_client_login(db_name: str, display_name: str = "") -> str:
    """Mint (or refresh) the client-portal login for a database.

    Returns a block of text listing the generated credentials, ready to append
    to a tool result. Any failure is swallowed on purpose — a problem minting a
    login must never undo a database that was created successfully.
    """
    try:
        from jarvis.auth import client_accounts
        account = client_accounts.provision_client_account(db_name, display_name=display_name)
        from jarvis.auth.service import get_auth_service
        get_auth_service().load_client_accounts()
    except Exception:
        log.warning("client login provisioning failed for %s", db_name, exc_info=True)
        return ""

    return (
        f"\n\nClient login generated for '{account.display_name}':"
        f"\n  email    {account.email}"
        f"\n  username {account.username}"
        f"\n  password {account.password}"
        "\nRe-open the Databases panel → 'Clients' tab to show or rotate it."
    )


# ---------------------------------------------------------------------------
# Tool: create_database
# ---------------------------------------------------------------------------

@tool(
    name="create_database",
    description=(
        "Create a brand-new MariaDB database with tables, its own app user, "
        "and an auto-generated admin interface in the Seline Databases panel. "
        "If no tables are given, the standard bar schema (products, purchases, "
        "sales, import_log + profit views) is created automatically. "
        "Every custom table gets an `id` primary key and a `created_at` timestamp."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Database name: lowercase letters, digits, underscores, starting with a letter (e.g. 'gym_members').",
            },
            "description": {
                "type": "string",
                "description": "Short human description shown in the Databases panel.",
            },
            "tables": {
                "type": "array",
                "description": "Tables to create.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Table name (same rules as database name)."},
                        "columns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "description": (
                                            "One of: INT, BIGINT, TINYINT(1), DECIMAL(10,2), "
                                            "VARCHAR(n) with n<=255, TEXT, DATE, DATETIME, TIMESTAMP."
                                        ),
                                    },
                                },
                                "required": ["name", "type"],
                            },
                        },
                    },
                    "required": ["name", "columns"],
                },
            },
        },
        "required": ["name"],
    },
)
def create_database(name: str, tables: list | None = None, description: str = "") -> str:
    """@tool wrapper — delegates to create_database_impl (also used by the
    server-side intent path)."""
    return create_database_impl(name, description, tables)


def create_database_impl(name: str, description: str = "", tables: list | None = None) -> str:
    name = (name or "").strip().lower()
    if not _IDENT_FIX.match(name):
        return "[Error] Invalid database name. Use lowercase letters, digits, underscores, starting with a letter."

    use_default_template = not tables
    normalized_tables = []
    if not use_default_template:
        # Validate everything before touching the server.
        for t in tables:
            tname = str((t or {}).get("name", "")).strip().lower()
            if not _IDENT_FIX.match(tname):
                return f"[Error] Invalid table name: {tname!r}"
            cols = (t or {}).get("columns") or []
            if not cols:
                return f"[Error] Table {tname!r} needs at least one column."
            norm_cols = []
            for c in cols:
                cname = str((c or {}).get("name", "")).strip().lower()
                ctype = str((c or {}).get("type", "")).strip().upper().replace(" ", "")
                if not _IDENT_FIX.match(cname):
                    return f"[Error] Invalid column name: {cname!r}"
                if cname in ("id", "created_at"):
                    continue
                if not _COL_TYPE.match(ctype):
                    return f"[Error] Unsupported column type {ctype!r} for {cname!r}."
                if ctype.startswith("VARCHAR("):
                    n = int(ctype[8:-1])
                    if n < 1 or n > 255:
                        return f"[Error] VARCHAR size out of range for {cname!r}."
                norm_cols.append((cname, ctype))
            normalized_tables.append((tname, norm_cols))

    creds = _admin_creds()
    if creds is None:
        return _ADMIN_HELP

    try:
        import mysql.connector
    except ImportError:
        return "[Error] mysql-connector-python is not installed in this environment."

    admin_user, admin_password = creds

    try:
        conn = mysql.connector.connect(
            host="127.0.0.1", port=3306,
            user=admin_user, password=admin_password,
            connection_timeout=5,
        )
        cur = conn.cursor()

        cur.execute(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
            (name,),
        )
        if cur.fetchone():
            cur.close()
            conn.close()
            login_note = _provision_client_login(name)
            return f"[Exists] Database '{name}' already exists.{login_note}"

        cur.execute(f"CREATE DATABASE `{name}`")
        cur.execute(f"USE `{name}`")

        if use_default_template:
            stmts = _load_template_statements() or (DEFAULT_BAR_SCHEMA_SQL + DEFAULT_BAR_VIEWS_SQL)
            for stmt in stmts:
                cur.execute(stmt)
            created_tables = ["products", "purchases", "sales", "import_log"]
        else:
            created_tables = []
            for tname, cols in normalized_tables:
                col_defs = ["`id` INT AUTO_INCREMENT PRIMARY KEY"]
                col_defs += [f"`{cn}` {ct}" for cn, ct in cols]
                col_defs.append("`created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                cur.execute(f"CREATE TABLE IF NOT EXISTS `{name}`.`{tname}` ({', '.join(col_defs)})")
                created_tables.append(tname)

        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        log.exception("create_database failed")
        return f"[Error] Database creation failed: {exc}"

    entries = [e for e in _load_registry() if e.get("name") != name]
    entries.append({
        "name": name,
        "user": admin_user,
        "password": admin_password,
        "description": description or f"Created by Jarvis ({datetime.now().date().isoformat()})",
        "display_name": "",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    _save_registry(entries)

    login_note = _provision_client_login(name)

    template_note = " (standard bar schema + profit views)" if use_default_template else ""
    return (
        f"Database '{name}' created{template_note} with {len(created_tables)} table(s): "
        f"{', '.join(created_tables)}. "
        f"It already has an admin interface: open the Databases panel (database "
        f"icon in the header) → tab '{name}'.{login_note}"
    )


# ---------------------------------------------------------------------------
# Tool: generate_database_ui
# ---------------------------------------------------------------------------

@tool(
    name="generate_database_ui",
    description=(
        "Register (or refresh) the auto-generated admin interface for a database "
        "in the Seline Databases panel: table browser, search, add/edit/delete "
        "row forms generated from the schema. Works on AI-created databases "
        "(they appear as tabs automatically); core databases always have tabs."
    ),
    parameters={
        "type": "object",
        "properties": {
            "database": {"type": "string", "description": "Database name (e.g. 'gym_members')."},
            "display_name": {"type": "string", "description": "Optional pretty label for the tab."},
            "description": {"type": "string", "description": "Optional description shown under the tab."},
        },
        "required": ["database"],
    },
)
def generate_database_ui(database: str, display_name: str = "", description: str = "") -> str:
    name = (database or "").strip().lower()
    env = _load_env()
    core_dbs = {env.get("DB_NAME"), env.get("AI_DB_NAME")} - {None, ""}

    if name in core_dbs:
        return (
            f"'{name}' is a core database — it already has a permanent tab in the "
            "Databases panel. Nothing to generate."
        )

    entry = _registry_entry(name)
    if entry is None:
        return (
            f"[Error] No registered database named {name!r}. "
            "Create it first with create_database, then ask me to generate its interface."
        )

    if display_name:
        entry["display_name"] = display_name.strip()
    if description:
        entry["description"] = description.strip()
    entries = [e if e.get("name") != name else entry for e in _load_registry()]
    _save_registry(entries)

    label = entry.get("display_name") or name
    return (
        f"Interface ready: open the Databases panel (database icon in the header) "
        f"→ tab '{label}'. It has a table browser, search, and add/edit/delete "
        "row forms generated from the live schema."
    )
