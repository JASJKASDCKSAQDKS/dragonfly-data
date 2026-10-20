"""
Per-database read-only MariaDB accounts for the client portal.

A client signs in with the credentials the app generated; the portal then
reads that business's data. To keep least privilege, the portal never reads
with the admin account — each database gets its own SELECT-only user,
mirroring the ``tenant_*`` users the tenant service already provisions.

When the admin account is not configured (or lacks CREATE USER rights) these
helpers report failure and the caller falls back to the registry credentials
so the portal still works.
"""

from __future__ import annotations

import logging
import re

from jarvis import config

log = logging.getLogger(__name__)

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def is_valid_db_name(db_name: str) -> bool:
    return bool(_IDENT.match(db_name or ""))


def readonly_username(db_name: str) -> str:
    """The MariaDB account name that reads ``db_name`` (e.g. client_mikes_bar)."""
    return f"client_{db_name}"


def _admin_connection():
    """Privileged connection used only to manage read-only users."""
    if not (config.ADMIN_DB_USER and config.ADMIN_DB_PASSWORD):
        return None
    try:
        import mysql.connector
    except ImportError:
        return None
    try:
        return mysql.connector.connect(
            host=config.DB_HOST or "127.0.0.1",
            port=config.DB_PORT or 3306,
            user=config.ADMIN_DB_USER,
            password=config.ADMIN_DB_PASSWORD,
            connection_timeout=5,
        )
    except Exception:
        log.warning("admin connection for read-only user creation failed", exc_info=True)
        return None


def ensure_readonly_user(db_name: str, password: str) -> bool:
    """Create or re-key a SELECT-only account for ``db_name``.

    Returns True only when the account exists with the given password and
    holds SELECT on the database.
    """
    if not is_valid_db_name(db_name) or not password:
        return False
    conn = _admin_connection()
    if conn is None:
        return False
    user = readonly_username(db_name)
    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY %s",
            (password,),
        )
        cur.execute(f"ALTER USER '{user}'@'%' IDENTIFIED BY %s", (password,))
        cur.execute(f"GRANT SELECT ON `{db_name}`.* TO '{user}'@'%'")
        cur.execute("FLUSH PRIVILEGES")
        conn.commit()
        cur.close()
        return True
    except Exception:
        log.warning("could not provision read-only user for %s", db_name, exc_info=True)
        return False
    finally:
        conn.close()


def drop_readonly_user(db_name: str) -> None:
    """Remove the read-only account for a deleted database (best effort)."""
    if not is_valid_db_name(db_name):
        return
    conn = _admin_connection()
    if conn is None:
        return
    user = readonly_username(db_name)
    try:
        cur = conn.cursor()
        cur.execute(f"DROP USER IF EXISTS '{user}'@'%'")
        cur.execute("FLUSH PRIVILEGES")
        conn.commit()
        cur.close()
    except Exception:
        log.warning("could not drop read-only user for %s", db_name, exc_info=True)
    finally:
        conn.close()
