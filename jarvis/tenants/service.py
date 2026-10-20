"""
Tenant service for Jarvis.

Handles tenant provisioning, per-tenant read-only database user creation,
schema migrations, and tenant database lifecycle management.
"""

from __future__ import annotations

import logging
import os
import secrets
import subprocess
from pathlib import Path
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError

from jarvis import config
from jarvis.tenants.models import Tenant, TenantDBUser, TenantSettings

log = logging.getLogger(__name__)


class TenantService:
    """Service for managing tenants and their databases."""
    
    def __init__(self):
        self._tenants: dict[int, Tenant] = {}
        self._tenant_settings: dict[int, TenantSettings] = {}
        self._next_tenant_id = 1
        
        # Ensure tenant DB directory exists
        Path(config.TENANT_DB_DIR).mkdir(parents=True, exist_ok=True)
        
        # Load existing tenants from registry
        self._load_registry()
    
    def _load_registry(self):
        """Load tenants from registry file."""
        import json
        registry_path = Path(config.TENANT_REGISTRY_PATH)
        if registry_path.exists():
            try:
                with open(registry_path) as f:
                    data = json.load(f)
                for t_data in data:
                    tenant = Tenant(**t_data)
                    self._tenants[tenant.id] = tenant
                    if tenant.id >= self._next_tenant_id:
                        self._next_tenant_id = tenant.id + 1
                log.info(f"Loaded {len(self._tenants)} tenants from registry")
            except Exception as e:
                log.error(f"Failed to load tenant registry: {e}")
    
    def _save_registry(self):
        """Save tenants to registry file."""
        import json
        registry_path = Path(config.TENANT_REGISTRY_PATH)
        data = []
        for tenant in self._tenants.values():
            data.append({
                "id": tenant.id,
                "name": tenant.name,
                "display_name": tenant.display_name,
                "db_name": tenant.db_name,
                "db_user": tenant.db_user,
                "db_password": tenant.db_password,
                "status": tenant.status,
                "timezone": tenant.timezone,
                "business_day_start_hour": tenant.business_day_start_hour,
                "created_at": tenant.created_at.isoformat(),
                "updated_at": tenant.updated_at.isoformat(),
            })
        try:
            with open(registry_path, "w") as f:
                json.dump(data, f, indent=2)
            try:
                os.chmod(registry_path, 0o600)
            except OSError:
                pass
        except Exception as e:
            log.error(f"Failed to save tenant registry: {e}")
    
    def _get_admin_connection(self):
        """Get admin connection to MariaDB (for provisioning only)."""
        if not config.ADMIN_DB_USER or not config.ADMIN_DB_PASSWORD:
            raise RuntimeError("Admin DB credentials not configured. Set ADMIN_DB_USER and ADMIN_DB_PASSWORD in .env")
        
        return mysql.connector.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.ADMIN_DB_USER,
            password=config.ADMIN_DB_PASSWORD,
            connection_timeout=5,
        )
    
    def _get_tenant_connection(self, tenant: Tenant, read_only: bool = True):
        """Get connection to tenant's database."""
        user = tenant.db_user if read_only else config.ADMIN_DB_USER
        password = tenant.db_password if read_only else config.ADMIN_DB_PASSWORD
        
        return mysql.connector.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=user,
            password=password,
            database=tenant.db_name,
            connection_timeout=5,
        )
    
    def create_tenant(
        self,
        name: str,
        display_name: str,
        timezone: str = "UTC",
        business_day_start_hour: int = 6,
    ) -> Tenant:
        """Create a new tenant with database and read-only user."""
        # Validate name
        if not name or not name[0].isalpha():
            raise ValueError("Tenant name must start with a letter")
        if not all(c.isalnum() or c == '_' for c in name):
            raise ValueError("Tenant name must contain only letters, numbers, and underscores")
        if len(name) > 63:
            raise ValueError("Tenant name too long (max 63 chars)")
        
        # Check if tenant already exists
        for t in self._tenants.values():
            if t.name == name:
                raise ValueError(f"Tenant '{name}' already exists")
            if t.db_name == name:
                raise ValueError(f"Database name '{name}' already exists")
        
        # Generate credentials
        db_name = name
        db_user = f"tenant_{name}"
        db_password = secrets.token_urlsafe(24)
        
        # Create tenant object
        tenant = Tenant(
            id=self._next_tenant_id,
            name=name,
            display_name=display_name,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
            timezone=timezone,
            business_day_start_hour=business_day_start_hour,
        )
        self._next_tenant_id += 1
        
        # Provision database and user
        self._provision_tenant_database(tenant)
        
        # Save tenant
        self._tenants[tenant.id] = tenant
        self._save_registry()
        
        # Create default settings
        self._tenant_settings[tenant.id] = TenantSettings(tenant_id=tenant.id)
        
        # Mint the client-portal login so the owner can reach the client interface.
        self._provision_client_login(tenant)

        log.info(f"Created tenant: {tenant.name} (id={tenant.id})")
        return tenant
    
    def _provision_tenant_database(self, tenant: Tenant):
        """Provision tenant database with schema and read-only user."""
        admin_conn = self._get_admin_connection()
        try:
            cursor = admin_conn.cursor()
            
            # Create database
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{tenant.db_name}`")
            cursor.execute(f"USE `{tenant.db_name}`")
            
            # Load and execute schema template
            schema_path = Path(config.TENANT_DB_TEMPLATE)
            if schema_path.exists():
                with open(schema_path) as f:
                    schema_sql = f.read()
                
                # Split by semicolon and execute each statement
                schema_sql = "\n".join(
                    line for line in schema_sql.splitlines()
                    if not line.strip().startswith("--")
                )
                for statement in schema_sql.split(';'):
                    statement = statement.strip()
                    if statement and not statement.startswith('--'):
                        cursor.execute(statement)
            else:
                # Fallback to default schema
                self._create_default_schema(cursor)
            self._apply_additive_migrations(cursor)
            
            # Create read-only user
            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{tenant.db_user}'@'%' IDENTIFIED BY %s",
                (tenant.db_password,)
            )
            
            # Grant SELECT only on tenant's database
            cursor.execute(
                f"GRANT SELECT ON `{tenant.db_name}`.* TO '{tenant.db_user}'@'%'"
            )
            
            # Flush privileges
            cursor.execute("FLUSH PRIVILEGES")
            
            admin_conn.commit()
            cursor.close()
            
            log.info(f"Provisioned database for tenant: {tenant.name}")
            
        except MySQLError as e:
            admin_conn.rollback()
            log.error(f"Failed to provision tenant database: {e}")
            raise
        finally:
            admin_conn.close()

    def _apply_additive_migrations(self, cursor) -> None:
        """Apply bundled, repeatable migrations to an existing tenant database."""
        migration = Path(config.PROJECT_ROOT) / "templates" / "migrations" / "001_phase1.sql"
        if not migration.exists():
            return
        migration_sql = "\n".join(
            line for line in migration.read_text().splitlines()
            if not line.strip().startswith("--")
        )
        for statement in migration_sql.split(";"):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
    
    def _create_default_schema(self, cursor):
        """Create default bar schema (fallback if template not found)."""
        statements = [
            """CREATE TABLE IF NOT EXISTS products (
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
            # Indexes are defined inline in the tables above — MariaDB does
            # not support CREATE INDEX ... IF NOT EXISTS.
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
        
        for stmt in statements:
            cursor.execute(stmt)
    
    def _provision_client_login(self, tenant: Tenant) -> None:
        """Mint the client-portal login that opens this tenant's database.

        Best-effort: a failure here must not roll back a provisioned tenant.
        """
        try:
            from jarvis.auth import client_accounts
            account = client_accounts.provision_client_account(
                db_name=tenant.db_name,
                display_name=tenant.display_name,
                tenant_id=tenant.id,
                db_user=tenant.db_user,
                db_password=tenant.db_password,
            )
            from jarvis.auth.service import get_auth_service
            get_auth_service().load_client_accounts()
            log.info("Client login for tenant %s: %s", tenant.name, account.email)
        except Exception:
            log.warning(
                "client login provisioning failed for tenant %s",
                tenant.name, exc_info=True,
            )

    def get_tenant(self, tenant_id: int) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)
    
    def get_tenant_by_name(self, name: str) -> Optional[Tenant]:
        for t in self._tenants.values():
            if t.name == name:
                return t
        return None
    
    def get_tenant_by_db_name(self, db_name: str) -> Optional[Tenant]:
        for t in self._tenants.values():
            if t.db_name == db_name:
                return t
        return None
    
    def list_tenants(self) -> list[Tenant]:
        return list(self._tenants.values())
    
    def suspend_tenant(self, tenant_id: int) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.status = "suspended"
        tenant.updated_at = datetime.now(timezone.utc)
        self._save_registry()
        return True
    
    def reactivate_tenant(self, tenant_id: int) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        tenant.status = "active"
        tenant.updated_at = datetime.now(timezone.utc)
        self._save_registry()
        return True
    
    def delete_tenant(self, tenant_id: int) -> bool:
        """Delete tenant and its database (irreversible!)."""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False
        
        # Drop database and user
        admin_conn = self._get_admin_connection()
        try:
            cursor = admin_conn.cursor()
            cursor.execute(f"DROP DATABASE IF EXISTS `{tenant.db_name}`")
            cursor.execute(f"DROP USER IF EXISTS '{tenant.db_user}'@'%'")
            cursor.execute("FLUSH PRIVILEGES")
            admin_conn.commit()
            cursor.close()
        except MySQLError as e:
            log.error(f"Failed to drop tenant database: {e}")
            raise
        finally:
            admin_conn.close()
        
        # Remove from registry
        del self._tenants[tenant_id]
        if tenant_id in self._tenant_settings:
            del self._tenant_settings[tenant_id]
        self._save_registry()
        
        log.info(f"Deleted tenant: {tenant.name}")
        return True
    
    def get_settings(self, tenant_id: int) -> TenantSettings:
        if tenant_id not in self._tenant_settings:
            self._tenant_settings[tenant_id] = TenantSettings(tenant_id=tenant_id)
        return self._tenant_settings[tenant_id]
    
    def update_settings(self, tenant_id: int, settings: TenantSettings) -> TenantSettings:
        self._tenant_settings[tenant_id] = settings
        return settings
    
    def run_migrations(self, tenant_id: int) -> bool:
        """Run additive tenant migrations (Alembic when configured, SQL fallback)."""
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return False
        
        try:
            env = os.environ.copy()
            env["TENANT_DB_NAME"] = tenant.db_name
            env["TENANT_DB_USER"] = config.ADMIN_DB_USER
            env["TENANT_DB_PASSWORD"] = config.ADMIN_DB_PASSWORD
            
            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                cwd=config.PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                log.warning("Alembic unavailable or not configured; applying additive SQL")
                conn = self._get_tenant_connection(tenant, read_only=False)
                try:
                    self._apply_additive_migrations(conn.cursor())
                    conn.commit()
                finally:
                    conn.close()
            
            log.info(f"Migrations applied for tenant: {tenant.name}")
            return True
        except Exception as e:
            log.error(f"Migration error for tenant {tenant.name}: {e}")
            return False
    
    def test_tenant_connection(self, tenant_id: int, read_only: bool = True) -> bool:
        """Test connection to tenant database."""
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return False
        
        try:
            conn = self._get_tenant_connection(tenant, read_only=read_only)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            log.error(f"Connection test failed for tenant {tenant.name}: {e}")
            return False


# Global singleton
_tenant_service: Optional[TenantService] = None


def get_tenant_service() -> TenantService:
    """Get the global TenantService singleton."""
    global _tenant_service
    if _tenant_service is None:
        _tenant_service = TenantService()
    return _tenant_service
