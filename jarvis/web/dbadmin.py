"""
Database admin API — browse and edit any registered MariaDB database.

Powers the Seline UI's Databases panel: list databases/tables, introspect
schema, paginate rows, insert/update/delete rows, and per-database activity
feeds. AI-created databases (registered in tenant registry)
appear automatically.

Safety: database/table/column identifiers are validated against a strict
whitelist and must exist in the registered set; every value is parameterized;
columns whose name contains "pass" are SHA-256 hashed on write and masked
on read.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
from decimal import Decimal

import mysql.connector
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from jarvis import config
from jarvis.tools.db_tools import (
    _COL_TYPE,
    _load_registry as _tools_load_registry,
    _save_registry as _tools_save_registry,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dbadmin")

# The project's own .env (loaded by config) — not a relocated ~/.jarvis path.
_ENV_PATH = str(config.PROJECT_ROOT / ".env")
# AI-created-database registry (distinct from the tenant registry).
_REGISTRY_PATH = config.DB_REGISTRY_PATH

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_PASSWORD_COL = re.compile(r"pass", re.IGNORECASE)
_MASK = "••••••••"
_MAX_ROWS = 100

# MariaDB's internal schemas — never shown in the panel.
_SYSTEM_DBS = {"information_schema", "performance_schema", "mysql", "sys"}


# ---------------------------------------------------------------------------
# Credentials + registry
# ---------------------------------------------------------------------------

def _load_env() -> dict:
    """Database credentials from the project .env.

    Reads the file directly and lets values already present in the process
    environment (populated by dotenv from the same file) win, so the panel
    and the running config never disagree.
    """
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
    for key in (
        "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
        "AI_DB_NAME", "AI_DB_USER", "AI_DB_PASSWORD",
        "ADMIN_DB_USER", "ADMIN_DB_PASSWORD",
    ):
        val = os.environ.get(key)
        if val:
            values[key] = val
    return values


def _admin_creds() -> tuple[str, str] | None:
    """Privileged MariaDB credentials, or None when unconfigured."""
    env = _load_env()
    user = env.get("ADMIN_DB_USER") or config.ADMIN_DB_USER
    password = env.get("ADMIN_DB_PASSWORD") or config.ADMIN_DB_PASSWORD
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


def _cred_map() -> dict:
    """Map of database name -> connection info + display metadata.

    Sources, in order:
      1. Core databases from the project .env (bar1_db, ai_memory).
      2. AI-created databases from the registry (with descriptions).
      3. Every other database discovered live on the MariaDB server, so
         databases that exist but aren't registered still appear.
    """
    env = _load_env()
    out: dict[str, dict] = {}

    if env.get("DB_NAME"):
        out[env["DB_NAME"]] = {
            "user": env.get("DB_USER", ""),
            "password": env.get("DB_PASSWORD", ""),
            "source": "core",
            "description": "Bar 1 — sales & purchases",
        }
    if env.get("AI_DB_NAME"):
        out[env["AI_DB_NAME"]] = {
            "user": env.get("AI_DB_USER", ""),
            "password": env.get("AI_DB_PASSWORD", ""),
            "source": "core",
            "description": "AI long-term memory",
        }

    for entry in _load_registry():
        name = entry.get("name", "")
        if name and _IDENT.match(name):
            out[name] = {
                "user": entry.get("user", ""),
                "password": entry.get("password", ""),
                "source": "ai-created",
                "description": entry.get("description", ""),
                "display_name": entry.get("display_name", ""),
            }

    # Discover anything else on the server via the privileged user.
    admin = _admin_creds()
    if admin:
        try:
            conn = mysql.connector.connect(
                host=env.get("DB_HOST", "127.0.0.1"),
                port=int(env.get("DB_PORT", 3306)),
                user=admin[0], password=admin[1],
                connection_timeout=3,
            )
            cur = conn.cursor()
            cur.execute("SHOW DATABASES")
            for (name,) in cur.fetchall():
                if name in _SYSTEM_DBS or not _IDENT.match(name) or name in out:
                    continue
                out[name] = {
                    "user": admin[0],
                    "password": admin[1],
                    "source": "discovered",
                    "description": "",
                }
            cur.close()
            conn.close()
        except Exception:
            log.warning("database discovery failed", exc_info=True)

    return out


def _connect(db: str):
    info = _cred_map().get(db)
    if info is None:
        return None
    return mysql.connector.connect(
        host="127.0.0.1",
        port=3306,
        user=info["user"],
        password=info["password"],
        database=db,
        connection_timeout=3,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_ident(value: str) -> bool:
    return bool(_IDENT.match(value or ""))


def _clean(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime.datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return str(value)
    return value


def _clean_row(row: dict) -> dict:
    return {k: _clean(v) for k, v in row.items()}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "error", "message": message})


def _get_columns(conn, db: str, table: str) -> list[dict]:
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, EXTRA "
        "FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
        (db, table),
    )
    cols = cur.fetchall()
    cur.close()
    return cols


def _primary_key(columns: list[dict]) -> str | None:
    for c in columns:
        if c["COLUMN_KEY"] == "PRI":
            return c["COLUMN_NAME"]
    return None


def _table_exists(conn, db: str, table: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
        (db, table),
    )
    n = cur.fetchone()[0]
    cur.close()
    return n > 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/databases")
async def list_databases():
    try:
        out = []
        for name, info in _cred_map().items():
            entry = {
                "name": name,
                "source": info["source"],
                "description": info.get("description", ""),
                "display_name": info.get("display_name", ""),
                "tables": 0,
                "reachable": True,
            }
            try:
                conn = _connect(name)
                cur = conn.cursor()
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'",
                    (name,),
                )
                entry["tables"] = cur.fetchone()[0]
                cur.close()
                conn.close()
            except Exception:
                entry["reachable"] = False
            out.append(entry)
        return JSONResponse({"status": "success", "databases": out})
    except Exception as e:
        log.exception("list_databases failed")
        return _error(500, str(e))


@router.get("/{db}/tables")
async def list_tables(db: str):
    if not _valid_ident(db) or db not in _cred_map():
        return _error(404, "Unknown database.")
    try:
        conn = _connect(db)
        cur = conn.cursor()
        cur.execute(
            "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE IN ('BASE TABLE', 'VIEW') "
            "ORDER BY TABLE_TYPE, TABLE_NAME",
            (db,),
        )
        rows = cur.fetchall()
        tables = []
        for tname, ttype in rows:
            cur.execute(f"SELECT COUNT(*) FROM `{tname}`")
            tables.append({
                "name": tname,
                "rows": cur.fetchone()[0],
                "kind": "view" if ttype == "VIEW" else "table",
            })
        cur.close()
        conn.close()
        return JSONResponse({"status": "success", "tables": tables})
    except Exception as e:
        log.exception("list_tables failed")
        return _error(500, str(e))


@router.get("/{db}/{table}/schema")
async def table_schema(db: str, table: str):
    if not (_valid_ident(db) and _valid_ident(table)) or db not in _cred_map():
        return _error(404, "Unknown database or table.")
    try:
        conn = _connect(db)
        if not _table_exists(conn, db, table):
            conn.close()
            return _error(404, "Unknown table.")
        cols = _get_columns(conn, db, table)
        conn.close()
        out = [
            {
                "name": c["COLUMN_NAME"],
                "type": c["COLUMN_TYPE"],
                "nullable": c["IS_NULLABLE"] == "YES",
                "key": c["COLUMN_KEY"],
                "default": _clean(c["COLUMN_DEFAULT"]),
                "extra": c["EXTRA"],
                "secret": bool(_PASSWORD_COL.search(c["COLUMN_NAME"])),
            }
            for c in cols
        ]
        return JSONResponse({"status": "success", "columns": out})
    except Exception as e:
        log.exception("table_schema failed")
        return _error(500, str(e))


@router.get("/{db}/{table}/rows")
async def table_rows(db: str, table: str, limit: int = 50, offset: int = 0, search: str = ""):
    if not (_valid_ident(db) and _valid_ident(table)) or db not in _cred_map():
        return _error(404, "Unknown database or table.")
    limit = max(1, min(limit, _MAX_ROWS))
    offset = max(0, offset)
    try:
        conn = _connect(db)
        if not _table_exists(conn, db, table):
            conn.close()
            return _error(404, "Unknown table.")
        cols = _get_columns(conn, db, table)
        col_names = [c["COLUMN_NAME"] for c in cols]

        where, params = "", []
        if search.strip():
            text_cols = [
                c["COLUMN_NAME"] for c in cols
                if any(t in c["COLUMN_TYPE"].lower() for t in ("char", "text"))
            ]
            if text_cols:
                where = " WHERE " + " OR ".join(f"`{c}` LIKE %s" for c in text_cols)
                params = [f"%{search.strip()}%"] * len(text_cols)

        cur = conn.cursor(dictionary=True)
        cur.execute(f"SELECT COUNT(*) FROM `{table}`{where}", params)
        total = cur.fetchone()["COUNT(*)"]
        cur.execute(
            f"SELECT * FROM `{table}`{where} LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        rows = [_clean_row(r) for r in cur.fetchall()]
        cur.close()
        conn.close()

        for row in rows:
            for c in col_names:
                if _PASSWORD_COL.search(c) and row.get(c):
                    row[c] = _MASK

        return JSONResponse({
            "status": "success",
            "columns": col_names,
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    except Exception as e:
        log.exception("table_rows failed")
        return _error(500, str(e))


@router.post("/{db}/{table}/rows")
async def insert_row(db: str, table: str, body: dict):
    if not (_valid_ident(db) and _valid_ident(table)) or db not in _cred_map():
        return _error(404, "Unknown database or table.")
    try:
        conn = _connect(db)
        if not _table_exists(conn, db, table):
            conn.close()
            return _error(404, "Unknown table.")
        cols = _get_columns(conn, db, table)
        writable = [
            c for c in cols
            if "auto_increment" not in c["EXTRA"].lower()
            and "generated" not in c["EXTRA"].lower()
        ]
        writable_names = {c["COLUMN_NAME"] for c in writable}
        data = {k: v for k, v in (body or {}).items() if k in writable_names}
        if not data:
            conn.close()
            return _error(422, "No writable columns provided.")
        for k, v in data.items():
            if _PASSWORD_COL.search(k) and isinstance(v, str) and v:
                data[k] = hashlib.sha256(v.encode()).hexdigest()

        names = list(data.keys())
        placeholders = ", ".join(["%s"] * len(names))
        sql = f"INSERT INTO `{table}` ({', '.join(f'`{n}`' for n in names)}) VALUES ({placeholders})"
        cur = conn.cursor()
        try:
            cur.execute(sql, [data[n] for n in names])
            conn.commit()
        except mysql.connector.Error as sql_err:
            conn.close()
            return _error(422, str(sql_err))
        new_id = cur.lastrowid
        cur.close()
        conn.close()
        return JSONResponse({"status": "success", "id": new_id})
    except Exception as e:
        log.exception("insert_row failed")
        return _error(500, str(e))


@router.put("/{db}/{table}/rows/{pk}")
async def update_row(db: str, table: str, pk: str, body: dict):
    if not (_valid_ident(db) and _valid_ident(table)) or db not in _cred_map():
        return _error(404, "Unknown database or table.")
    try:
        conn = _connect(db)
        if not _table_exists(conn, db, table):
            conn.close()
            return _error(404, "Unknown table.")
        cols = _get_columns(conn, db, table)
        pk_col = _primary_key(cols)
        if not pk_col:
            conn.close()
            return _error(422, "Table has no primary key.")
        writable_names = {
            c["COLUMN_NAME"] for c in cols
            if "auto_increment" not in c["EXTRA"].lower()
            and "generated" not in c["EXTRA"].lower()
            and c["COLUMN_KEY"] != "PRI"
        }
        data = {k: v for k, v in (body or {}).items() if k in writable_names}
        if not data:
            conn.close()
            return _error(422, "No writable columns provided.")
        for k in list(data.keys()):
            v = data[k]
            if _PASSWORD_COL.search(k):
                if isinstance(v, str) and v and v != _MASK:
                    data[k] = hashlib.sha256(v.encode()).hexdigest()
                else:
                    # Empty/masked password field on edit = keep existing hash.
                    del data[k]

        if not data:
            conn.close()
            return _error(422, "Nothing to update.")
        sets = ", ".join(f"`{k}` = %s" for k in data)
        cur = conn.cursor()
        cur.execute(
            f"UPDATE `{table}` SET {sets} WHERE `{pk_col}` = %s",
            (*data.values(), pk),
        )
        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()
        return JSONResponse({"status": "success", "affected": affected})
    except Exception as e:
        log.exception("update_row failed")
        return _error(500, str(e))


@router.delete("/{db}/{table}/rows/{pk}")
async def delete_row(db: str, table: str, pk: str):
    if not (_valid_ident(db) and _valid_ident(table)) or db not in _cred_map():
        return _error(404, "Unknown database or table.")
    try:
        conn = _connect(db)
        if not _table_exists(conn, db, table):
            conn.close()
            return _error(404, "Unknown table.")
        cols = _get_columns(conn, db, table)
        pk_col = _primary_key(cols)
        if not pk_col:
            conn.close()
            return _error(422, "Table has no primary key.")
        cur = conn.cursor()
        cur.execute(f"DELETE FROM `{table}` WHERE `{pk_col}` = %s", (pk,))
        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()
        return JSONResponse({"status": "success", "affected": affected})
    except Exception as e:
        log.exception("delete_row failed")
        return _error(500, str(e))


@router.get("/{db}/activity")
async def db_activity(db: str):
    if not _valid_ident(db) or db not in _cred_map():
        return _error(404, "Unknown database.")
    try:
        conn = _connect(db)
        items = []
        cur = conn.cursor(dictionary=True)

        if _table_exists(conn, db, "import_log"):
            cur.execute(
                "SELECT filename, import_type, rows_imported, rows_skipped, imported_at "
                "FROM import_log ORDER BY imported_at DESC LIMIT 10"
            )
            for r in cur.fetchall():
                items.append({
                    "kind": "import",
                    "text": f"{r['import_type']} import: {r['rows_imported']} rows "
                            f"({r['rows_skipped']} skipped) from {r['filename']}",
                    "ts": _clean(r["imported_at"]),
                })

        if _table_exists(conn, db, "memories"):
            cur.execute(
                "SELECT category, content, source, created_at FROM memories "
                "ORDER BY created_at DESC LIMIT 10"
            )
            for r in cur.fetchall():
                items.append({
                    "kind": "memory",
                    "text": f"[{r['category']}] {r['content'][:120]} (via {r['source']})",
                    "ts": _clean(r["created_at"]),
                })

        if _table_exists(conn, db, "conversations"):
            cur.execute(
                "SELECT role, content, created_at FROM conversations "
                "ORDER BY created_at DESC LIMIT 10"
            )
            for r in cur.fetchall():
                items.append({
                    "kind": "chat",
                    "text": f"{r['role']}: {r['content'][:120]}",
                    "ts": _clean(r["created_at"]),
                })

        cur.close()
        conn.close()
        items.sort(key=lambda x: str(x["ts"]), reverse=True)
        return JSONResponse({"status": "success", "activity": items[:20]})
    except Exception as e:
        log.exception("db_activity failed")
        return _error(500, str(e))


# ---------------------------------------------------------------------------
# Structural operations — delete database, add column
# ---------------------------------------------------------------------------

@router.delete("/{db}")
async def delete_database(db: str):
    """Drop an AI-created database and unregister it.

    Core databases (bar1_db, ai_memory) are protected: dropping them by
    accident would break the bar system or the AI's memory, so they must be
    dropped manually if ever needed.
    """
    if not _valid_ident(db):
        return _error(404, "Unknown database.")
    info = _cred_map().get(db)
    if info is None:
        return _error(404, "Unknown database.")
    if info["source"] == "core":
        return _error(
            403,
            f"'{db}' is a core database and cannot be deleted from the panel "
            "(it would break the system). AI-created databases can be deleted.",
        )

    try:
        conn = mysql.connector.connect(
            host="127.0.0.1", port=3306,
            user=info["user"], password=info["password"],
            connection_timeout=3,
        )
        cur = conn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.exception("delete_database failed")
        return _error(500, str(e))

    try:
        _tools_save_registry(
            [e for e in _tools_load_registry() if e.get("name") != db]
        )
    except Exception:
        log.exception("registry update after drop failed")
    return JSONResponse({"status": "success", "dropped": db})


@router.post("/{db}/{table}/columns")
async def add_column(db: str, table: str, body: dict):
    """Add a column to an existing table (ALTER TABLE ... ADD COLUMN)."""
    if not (_valid_ident(db) and _valid_ident(table)) or db not in _cred_map():
        return _error(404, "Unknown database or table.")

    col_name = str((body or {}).get("name", "")).strip().lower()
    col_type = str((body or {}).get("type", "")).strip().upper().replace(" ", "")
    if not _valid_ident(col_name):
        return _error(422, "Invalid column name. Use letters, digits, underscores, starting with a letter.")
    if not _COL_TYPE.match(col_type):
        return _error(
            422,
            f"Unsupported type {col_type!r}. Allowed: INT, BIGINT, TINYINT(1), "
            "DECIMAL(10,2), VARCHAR(n) n<=255, TEXT, DATE, DATETIME, TIMESTAMP.",
        )
    if col_type.startswith("VARCHAR("):
        n = int(col_type[8:-1])
        if n < 1 or n > 255:
            return _error(422, "VARCHAR size must be 1-255.")

    try:
        conn = _connect(db)
        cur = conn.cursor()
        cur.execute(
            "SELECT TABLE_TYPE FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            (db, table),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return _error(404, "Unknown table.")
        if row[0] == "VIEW":
            cur.close()
            conn.close()
            return _error(422, "Cannot add columns to a view.")

        cur.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
            (db, table, col_name),
        )
        if cur.fetchone()[0] > 0:
            cur.close()
            conn.close()
            return _error(422, f"Column '{col_name}' already exists.")

        try:
            cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col_name}` {col_type}")
            conn.commit()
        except mysql.connector.Error as sql_err:
            cur.close()
            conn.close()
            return _error(422, str(sql_err))

        cur.close()
        conn.close()
        return JSONResponse({"status": "success", "column": col_name, "type": col_type})
    except Exception as e:
        log.exception("add_column failed")
        return _error(500, str(e))


# ---------------------------------------------------------------------------
# Standard template editing — add columns / seed rows for FUTURE databases
# ---------------------------------------------------------------------------

_TEMPLATE_SQL_PATH = config.TENANT_DB_TEMPLATE

_CREATE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)\s*\((.*?)\)\s*;", re.IGNORECASE | re.DOTALL)
_ALTER_RE = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+)\s+([^;]+);", re.IGNORECASE)
_INSERT_RE = re.compile(r"INSERT INTO (\w+)", re.IGNORECASE)


def _template_structure() -> dict:
    """Parse standard_bar.sql into {table: {"columns": [...], "seed_rows": n}}."""
    try:
        with open(_TEMPLATE_SQL_PATH) as f:
            text = f.read()
    except FileNotFoundError:
        return {}

    structure: dict[str, dict] = {}
    for m in _CREATE_TABLE_RE.finditer(text):
        table = m.group(1)
        body = m.group(2)
        cols = []
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            first = line.split()[0].strip("`")
            if first.upper() in ("PRIMARY", "FOREIGN", "CONSTRAINT", "UNIQUE", "INDEX", "KEY"):
                continue
            col_type = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
            cols.append({"name": first, "type": col_type})
        structure.setdefault(table, {"columns": cols, "seed_rows": 0})

    for m in _ALTER_RE.finditer(text):
        table, col, col_type = m.group(1), m.group(2), m.group(3).strip()
        if table in structure:
            structure[table]["columns"].append({"name": col, "type": col_type})

    for m in _INSERT_RE.finditer(text):
        table = m.group(1)
        if table in structure:
            structure[table]["seed_rows"] += 1

    return structure


@router.get("/template/structure")
async def template_structure():
    """The standard template's tables/columns/seed counts (for the panel)."""
    try:
        structure = _template_structure()
        tables = [
            {"name": name, "columns": info["columns"], "seed_rows": info["seed_rows"]}
            for name, info in structure.items()
        ]
        return JSONResponse({"status": "success", "tables": tables, "path": _TEMPLATE_SQL_PATH})
    except Exception as e:
        log.exception("template_structure failed")
        return _error(500, str(e))


@router.post("/template/columns")
async def template_add_column(body: dict):
    """Append an ALTER TABLE ... ADD COLUMN to the template (affects FUTURE DBs)."""
    table = str((body or {}).get("table", "")).strip().lower()
    col_name = str((body or {}).get("name", "")).strip().lower()
    col_type = str((body or {}).get("type", "")).strip().upper().replace(" ", "")

    structure = _template_structure()
    if table not in structure:
        return _error(404, f"Table '{table}' is not in the template.")
    if not _valid_ident(col_name):
        return _error(422, "Invalid column name.")
    if any(c["name"] == col_name for c in structure[table]["columns"]):
        return _error(422, f"Column '{col_name}' already exists in template table '{table}'.")
    if not _COL_TYPE.match(col_type):
        return _error(422, f"Unsupported type {col_type!r}.")

    line = f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type};\n"
    try:
        with open(_TEMPLATE_SQL_PATH, "a") as f:
            f.write(f"\n-- added via Databases panel\n{line}")
    except Exception as e:
        log.exception("template_add_column failed")
        return _error(500, str(e))
    return JSONResponse({"status": "success", "appended": line.strip()})


@router.post("/template/rows")
async def template_add_row(body: dict):
    """Append an INSERT seed row to the template (affects FUTURE DBs)."""
    table = str((body or {}).get("table", "")).strip().lower()
    values = (body or {}).get("values") or {}

    structure = _template_structure()
    if table not in structure:
        return _error(404, f"Table '{table}' is not in the template.")

    known = {c["name"] for c in structure[table]["columns"]}
    skip = {"product_id", "purchase_id", "sale_id", "import_id", "created_at"}
    data = {k: v for k, v in values.items() if k in known and k not in skip and _valid_ident(k)}
    if not data:
        return _error(422, "No valid columns provided.")

    def sql_val(v):
        if v is None:
            return "NULL"
        s = str(v)
        try:
            float(s)
            return s
        except ValueError:
            return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

    cols = ", ".join(data.keys())
    vals = ", ".join(sql_val(v) for v in data.values())
    line = f"INSERT INTO {table} ({cols}) VALUES ({vals});\n"
    try:
        with open(_TEMPLATE_SQL_PATH, "a") as f:
            f.write(f"\n-- seed row added via Databases panel\n{line}")
    except Exception as e:
        log.exception("template_add_row failed")
        return _error(500, str(e))
    return JSONResponse({"status": "success", "appended": line.strip()})
