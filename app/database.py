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
    """Създава нужните таблици ако не съществуват."""
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
                promo_code_used   TEXT,
                affiliate_commission REAL,
                order_amount      REAL,
                status            TEXT     DEFAULT 'completed',
                created_at        TEXT     NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS affiliates (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                name               TEXT NOT NULL,
                email              TEXT NOT NULL UNIQUE,
                hashed_password    TEXT NOT NULL,
                promo_code         TEXT NOT NULL UNIQUE,
                commission_percent REAL NOT NULL,
                total_earned       REAL NOT NULL DEFAULT 0,
                total_paid         REAL NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
    migrate_db()
    print(f"[DB] ✅ База данни инициализирана: {DB_PATH}")


def migrate_db() -> None:
    """Add new columns when they are missing."""
    with get_connection() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(orders)").fetchall()
        }
        if "esim_tran_no" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN esim_tran_no TEXT")
            conn.commit()
            print("[DB] ✅ Колона esim_tran_no добавена.")
        if "promo_code_used" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN promo_code_used TEXT")
            conn.commit()
            print("[DB] ✅ Колона promo_code_used добавена.")
        if "affiliate_commission" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN affiliate_commission REAL")
            conn.commit()
            print("[DB] ✅ Колона affiliate_commission добавена.")
        if "order_amount" not in columns:
            conn.execute("ALTER TABLE orders ADD COLUMN order_amount REAL")
            conn.commit()
            print("[DB] ✅ Колона order_amount добавена.")


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
    promo_code_used: str = "",
    affiliate_commission: Optional[float] = None,
    order_amount: Optional[float] = None,
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
        "promo_code_used": promo_code_used,
        "affiliate_commission": affiliate_commission,
        "order_amount": order_amount,
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
                promo_code_used,
                affiliate_commission,
                order_amount,
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
                :promo_code_used,
                :affiliate_commission,
                :order_amount,
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
    """Find an order by ICCID."""
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


def create_affiliate(
    name: str,
    email: str,
    hashed_password: str,
    promo_code: str,
    commission_percent: float,
    total_earned: float = 0.0,
    total_paid: float = 0.0,
) -> int:
    values = {
        "name": name,
        "email": email.strip().lower(),
        "hashed_password": hashed_password,
        "promo_code": promo_code.strip(),
        "commission_percent": commission_percent,
        "total_earned": total_earned,
        "total_paid": total_paid,
    }
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO affiliates (
                name,
                email,
                hashed_password,
                promo_code,
                commission_percent,
                total_earned,
                total_paid
            ) VALUES (
                :name,
                :email,
                :hashed_password,
                :promo_code,
                :commission_percent,
                :total_earned,
                :total_paid
            )
        """, values)
        conn.commit()
    return cursor.lastrowid


def get_affiliate_by_email(email: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM affiliates WHERE lower(email) = lower(?)",
            (email.strip(),),
        ).fetchone()
    return dict(row) if row else None


def get_affiliate_by_id(affiliate_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM affiliates WHERE id = ?",
            (affiliate_id,),
        ).fetchone()
    return dict(row) if row else None


def get_affiliate_by_promo_code(promo_code: str) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM affiliates WHERE upper(promo_code) = upper(?)",
            (promo_code.strip(),),
        ).fetchone()
    return dict(row) if row else None


def get_orders_by_promo_code(promo_code: str) -> List[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM orders
            WHERE upper(COALESCE(promo_code_used, '')) = upper(?)
            ORDER BY id DESC
            """,
            (promo_code.strip(),),
        ).fetchall()
    return [dict(row) for row in rows]


def update_affiliate_totals(
    affiliate_id: int,
    earned_delta: float = 0.0,
    paid_delta: float = 0.0,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE affiliates
            SET total_earned = total_earned + ?,
                total_paid = total_paid + ?
            WHERE id = ?
            """,
            (earned_delta, paid_delta, affiliate_id),
        )
        conn.commit()


def get_esim_tran_no_by_iccid(iccid: str) -> Optional[str]:
    """Return the esim_tran_no for an ICCID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT esim_tran_no FROM orders WHERE iccid = ?",
            (iccid,),
        ).fetchone()
    return row["esim_tran_no"] if row else None