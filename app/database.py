import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Optional


# Базата данни се създава в главната папка на проекта
DB_PATH = Path(__file__).resolve().parent.parent / "esim_portal.db"


def get_connection() -> sqlite3.Connection:
    """Връща connection към SQLite базата."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # резултатите като речник
    return conn


def init_db() -> None:
    """Създава таблицата orders ако не съществува."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id                INTEGER  PRIMARY KEY AUTOINCREMENT,
                stripe_session_id TEXT     NOT NULL UNIQUE,
                full_name         TEXT,
                email             TEXT,
                package_slug      TEXT,
                country           TEXT,
                gb                TEXT,
                duration          TEXT,
                iccid             TEXT,
                esim_tran_no      TEXT,
                qr_code_url       TEXT,
                smdp_address      TEXT,
                matching_id       TEXT,
                lang              TEXT,
                status            TEXT     DEFAULT 'completed',
                created_at        TEXT     NOT NULL
            )
        """)
        conn.commit()
    migrate_db()
    print(f"[DB] ✅ База данни инициализирана: {DB_PATH}")


def migrate_db() -> None:
    """Добавя нови колони ако липсват."""
    with get_connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(orders)").fetchall()
        }
        if "esim_tran_no" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN esim_tran_no TEXT")
            conn.commit()
            print("[DB] ✅ Колона esim_tran_no добавена.")


def save_order(
    stripe_session_id: str,
    full_name: str,
    email: str,
    package_slug: str,
    country: str,
    gb: str,
    duration: str,
    iccid: str,
    qr_code_url: str,
    esim_tran_no: str = "",
    smdp_address: str = "",
    matching_id: str  = "",
    lang: str         = "en",
    status: str       = "completed",
) -> int:
    """
    Записва поръчката в базата данни.
    Връща id на новия запис.
    """
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    values = {
        "stripe_session_id": stripe_session_id,
        "full_name": full_name,
        "email": email,
        "package_slug": package_slug,
        "country": country,
        "gb": gb,
        "duration": duration,
        "iccid": iccid,
        "esim_tran_no": esim_tran_no,
        "qr_code_url": qr_code_url,
        "smdp_address": smdp_address,
        "matching_id": matching_id,
        "lang": lang,
        "status": status,
        "created_at": created_at,
    }

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO orders (
                stripe_session_id,
                full_name,
                email,
                package_slug,
                country,
                gb,
                duration,
                iccid,
                esim_tran_no,
                qr_code_url,
                smdp_address,
                matching_id,
                lang,
                status,
                created_at
            ) VALUES (
                :stripe_session_id,
                :full_name,
                :email,
                :package_slug,
                :country,
                :gb,
                :duration,
                :iccid,
                :esim_tran_no,
                :qr_code_url,
                :smdp_address,
                :matching_id,
                :lang,
                :status,
                :created_at
            )
        """, values)
        conn.commit()

    print(f"[DB] ✅ Поръчка записана → id={cursor.lastrowid} | ICCID={iccid} | session={stripe_session_id[:20]}...")
    return cursor.lastrowid


def get_order_by_session(stripe_session_id: str) -> Optional[dict]:
    """Търси поръчка по Stripe session ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE stripe_session_id = ?",
            (stripe_session_id,)
        ).fetchone()
    return dict(row) if row else None


def get_order_by_iccid(iccid: str) -> Optional[dict]:
    """Търси поръчка по ICCID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE iccid = ?",
            (iccid,),
        ).fetchone()
    return dict(row) if row else None

def get_all_orders(status_filter: Optional[str] = None) -> List[dict]:
    """Връща всички поръчки, сортирани от най-новата."""
    with get_connection() as conn:
        if status_filter:
            rows = conn.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY id DESC",
                (status_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM orders ORDER BY id DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def get_esim_tran_no_by_iccid(iccid: str) -> Optional[str]:
    """Връща esim_tran_no по iccid."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT esim_tran_no FROM orders WHERE iccid = ?",
            (iccid,),
        ).fetchone()
    return row["esim_tran_no"] if row else None