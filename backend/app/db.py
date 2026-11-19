import json, os, threading
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / "backend" / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.environ.get("DB_PATH", "data/app.db")
_lock = threading.RLock()
_conn = None
POSTGRES = bool(DATABASE_URL)

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS items(item_code TEXT PRIMARY KEY, description TEXT, uom TEXT, category TEXT, item_type TEXT, standard_price REAL);
CREATE TABLE IF NOT EXISTS suppliers(supplier_id TEXT PRIMARY KEY, name TEXT, city TEXT, categories TEXT, status TEXT, on_time_pct REAL, quality_rating REAL);
CREATE TABLE IF NOT EXISTS plants(plant TEXT PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS po_history(po_number TEXT PRIMARY KEY, po_date TEXT, supplier_id TEXT, item_code TEXT, quantity REAL, uom TEXT, unit_price REAL, plant TEXT, delivered_on_time INTEGER);
CREATE TABLE IF NOT EXISTS contracts(contract_id TEXT PRIMARY KEY, supplier_id TEXT, start_date TEXT, end_date TEXT, value_cap REAL, consumed_value REAL, source TEXT, lines TEXT, added_by TEXT, added_at TEXT);
CREATE TABLE IF NOT EXISTS policies(id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT, effective_date TEXT, status TEXT, body TEXT, changes TEXT, source TEXT, created_by TEXT, created_at TEXT, approved_by TEXT, approved_at TEXT);
CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, source TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS pr_lines(id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER, pr_no TEXT, pr_line TEXT, created_at TEXT, requester TEXT, department TEXT, plant TEXT, item_code TEXT, description TEXT, quantity TEXT, uom TEXT, estimated_unit_price TEXT, need_by_date TEXT, urgency TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER, created_by TEXT, created_at TEXT, policy_versions TEXT, rows TEXT, requirements TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, group_id TEXT, kind TEXT, comment TEXT, payload TEXT, actor TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, actor TEXT, action TEXT, entity TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS chat_sessions(id TEXT PRIMARY KEY, state TEXT, updated_at TEXT);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS items(item_code TEXT PRIMARY KEY, description TEXT, uom TEXT, category TEXT, item_type TEXT, standard_price DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS suppliers(supplier_id TEXT PRIMARY KEY, name TEXT, city TEXT, categories TEXT, status TEXT, on_time_pct DOUBLE PRECISION, quality_rating DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS plants(plant TEXT PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS po_history(po_number TEXT PRIMARY KEY, po_date TEXT, supplier_id TEXT, item_code TEXT, quantity DOUBLE PRECISION, uom TEXT, unit_price DOUBLE PRECISION, plant TEXT, delivered_on_time INTEGER);
CREATE TABLE IF NOT EXISTS contracts(contract_id TEXT PRIMARY KEY, supplier_id TEXT, start_date TEXT, end_date TEXT, value_cap DOUBLE PRECISION, consumed_value DOUBLE PRECISION, source TEXT, lines TEXT, added_by TEXT, added_at TEXT);
CREATE TABLE IF NOT EXISTS policies(id BIGSERIAL PRIMARY KEY, version TEXT, effective_date TEXT, status TEXT, body TEXT, changes TEXT, source TEXT, created_by TEXT, created_at TEXT, approved_by TEXT, approved_at TEXT);
CREATE TABLE IF NOT EXISTS batches(id BIGSERIAL PRIMARY KEY, name TEXT, source TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS pr_lines(id BIGSERIAL PRIMARY KEY, batch_id BIGINT, pr_no TEXT, pr_line TEXT, created_at TEXT, requester TEXT, department TEXT, plant TEXT, item_code TEXT, description TEXT, quantity TEXT, uom TEXT, estimated_unit_price TEXT, need_by_date TEXT, urgency TEXT);
CREATE TABLE IF NOT EXISTS runs(id BIGSERIAL PRIMARY KEY, batch_id BIGINT, created_by TEXT, created_at TEXT, policy_versions TEXT, rows TEXT, requirements TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS actions(id BIGSERIAL PRIMARY KEY, run_id BIGINT, group_id TEXT, kind TEXT, comment TEXT, payload TEXT, actor TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS audit(id BIGSERIAL PRIMARY KEY, at TEXT, actor TEXT, action TEXT, entity TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS chat_sessions(id TEXT PRIMARY KEY, state TEXT, updated_at TEXT);
"""

def now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def conn():
    global _conn
    if POSTGRES and _conn is not None:
        try:
            if getattr(_conn, "closed", False):
                try:
                    _conn.close()
                except Exception:
                    pass
                _conn = None
                globals()["POSTGRES"] = False
        except Exception:
            _conn = None
            globals()["POSTGRES"] = False
    if _conn is None:
        if POSTGRES:
            try:
                import psycopg
                _conn = psycopg.connect(DATABASE_URL, autocommit=False, connect_timeout=5)
                with _lock:
                    with _conn.cursor() as cur:
                        for statement in (s.strip() for s in POSTGRES_SCHEMA.split(";") if s.strip()):
                            cur.execute(statement)
                    _conn.commit()
            except Exception as exc:
                print(f"PostgreSQL unavailable, falling back to SQLite: {exc}")
                globals()["POSTGRES"] = False
        if not POSTGRES:
            import sqlite3
            os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.executescript(SQLITE_SCHEMA)
    return _conn

def _sql(sql):
    return sql.replace("?", "%s") if POSTGRES else sql

def q(sql, args=()):
    global _conn
    with _lock:
        if POSTGRES:
            try:
                with conn().cursor() as cur:
                    cur.execute(_sql(sql), args)
                    rows = cur.fetchall()
                    names = [d.name for d in cur.description]
                    return [dict(zip(names, r)) for r in rows]
            except Exception as exc:
                print(f"PostgreSQL connection lost, switching to SQLite: {exc}")
                try:
                    _conn.close()
                except Exception:
                    pass
                _conn = None
                globals()["POSTGRES"] = False
        return [dict(r) for r in conn().execute(sql, args).fetchall()]

def x(sql, args=(), returning=False):
    global _conn
    with _lock:
        if POSTGRES:
            try:
                c = conn()
                statement = _sql(sql)
                is_insert = statement.lstrip().upper().startswith("INSERT")
                table_match = __import__("re").search(r"INSERT\s+INTO\s+(\w+)", statement, __import__("re").I)
                table = table_match.group(1).lower() if table_match else ""
                id_tables = {"policies", "batches", "pr_lines", "runs", "actions", "audit"}
                if is_insert and table in id_tables and "RETURNING" not in statement.upper():
                    statement += " RETURNING id"
                with c.cursor() as cur:
                    cur.execute(statement, args)
                    returns_id = is_insert and table in id_tables and "RETURNING" in statement.upper()
                    row = cur.fetchone() if returns_id else None
                    c.commit()
                    return row[0] if row else None
            except Exception as exc:
                print(f"PostgreSQL write lost, switching to SQLite: {exc}")
                try:
                    _conn.close()
                except Exception:
                    pass
                _conn = None
                globals()["POSTGRES"] = False
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid

def many(sql, rows):
    global _conn
    with _lock:
        if POSTGRES:
            try:
                c = conn()
                with c.cursor() as cur:
                    cur.executemany(_sql(sql), rows)
                c.commit()
                return
            except Exception as exc:
                print(f"PostgreSQL batch write lost, switching to SQLite: {exc}")
                try:
                    _conn.close()
                except Exception:
                    pass
                _conn = None
                globals()["POSTGRES"] = False
        conn().executemany(sql, rows)
        conn().commit()

def audit(actor, action, entity, detail=""):
    x("INSERT INTO audit(at,actor,action,entity,detail) VALUES(?,?,?,?,?)", (now(), actor or "anonymous", action, entity, detail if isinstance(detail, str) else json.dumps(detail, default=str)))

def reset_for_tests():
    global _conn
    if _conn:
        _conn.close()
    _conn = None
