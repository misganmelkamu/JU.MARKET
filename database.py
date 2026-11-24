"""
Lightweight SQLite storage for the sales bot.
No ORM, just small helper functions — easy to read and modify.
"""
import sqlite3
import time
import secrets
from contextlib import contextmanager

from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL,
                stock INTEGER,              -- NULL = unlimited
                file_path TEXT,             -- set if it's an auto-delivered file
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                unit_price REAL NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                total REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'awaiting_proof',
                -- awaiting_proof -> awaiting_confirmation -> paid/rejected
                proof_file_id TEXT,
                admin_note TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        """)


# ---------- users ----------

def upsert_user(user_id: int, username: str, first_name: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (id, username, first_name, joined_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET username=excluded.username, "
            "first_name=excluded.first_name",
            (user_id, username, first_name, int(time.time())),
        )


# ---------- products ----------

def add_product(category, name, description, price, stock=None, file_path=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO products (category, name, description, price, stock, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (category, name, description, price, stock, file_path),
        )
        return cur.lastrowid


def list_categories():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM products WHERE active=1 ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]


def list_products(category=None, active_only=True):
    with get_conn() as conn:
        q = "SELECT * FROM products"
        conds, params = [], []
        if category:
            conds.append("category = ?")
            params.append(category)
        if active_only:
            conds.append("active = 1")
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id"
        return conn.execute(q, params).fetchall()


def get_product(product_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()


def set_product_active(product_id, active: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE products SET active = ? WHERE id = ?", (int(active), product_id)
        )


def update_product_field(product_id, field, value):
    """field must be one of: name, description, price, stock"""
    assert field in ("name", "description", "price", "stock")
    with get_conn() as conn:
        conn.execute(f"UPDATE products SET {field} = ? WHERE id = ?", (value, product_id))


def decrement_stock(product_id, qty=1):
    with get_conn() as conn:
        conn.execute(
            "UPDATE products SET stock = stock - ? "
            "WHERE id = ? AND stock IS NOT NULL",
            (qty, product_id),
        )


# ---------- orders ----------

def _new_reference():
    return "ORD-" + secrets.token_hex(3).upper()


def create_order(user_id, username, product, quantity=1):
    ref = _new_reference()
    total = product["price"] * quantity
    now = int(time.time())
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO orders "
            "(reference, user_id, username, product_id, product_name, unit_price, "
            "quantity, total, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_proof', ?, ?)",
            (ref, user_id, username, product["id"], product["name"], product["price"],
             quantity, total, now, now),
        )
        return cur.lastrowid, ref


def attach_proof(order_id, file_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET proof_file_id = ?, status = 'awaiting_confirmation', "
            "updated_at = ? WHERE id = ?",
            (file_id, int(time.time()), order_id),
        )


def set_order_status(order_id, status, admin_note=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders SET status = ?, admin_note = ?, updated_at = ? WHERE id = ?",
            (status, admin_note, int(time.time()), order_id),
        )


def get_order(order_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def get_order_by_reference(reference):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE reference = ?", (reference,)
        ).fetchone()


def list_orders_for_user(user_id, limit=20):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()


def list_pending_orders(limit=50):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM orders WHERE status = 'awaiting_confirmation' "
            "ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()


def stats():
    with get_conn() as conn:
        total_orders = conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
        paid = conn.execute(
            "SELECT COUNT(*) c, COALESCE(SUM(total),0) s FROM orders WHERE status='paid'"
        ).fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) c FROM orders WHERE status='awaiting_confirmation'"
        ).fetchone()["c"]
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        return {
            "total_orders": total_orders,
            "paid_orders": paid["c"],
            "revenue": paid["s"],
            "pending_orders": pending,
            "users": users,
        }
