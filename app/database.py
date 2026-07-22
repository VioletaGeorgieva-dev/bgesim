import os
import sqlite3
import re
from pathlib import Path
from datetime import datetime
from typing import List, Optional


# ── Backend detection ────────────────────────────────────────────────────────
_DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://", 1)

USE_POSTGRES = _DATABASE_URL.startswith("postgresql://")

# SQLite path (used only when USE_POSTGRES is False)
DB_PATH = Path(__file__).resolve().parent.parent / "esim_portal.db"

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras


def get_connection():
    """Връща connection към базата данни (SQLite или PostgreSQL)."""
    if USE_POSTGRES:
        conn = psycopg2.connect(_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _ph() -> str:
    """Placeholder: '%s' за PostgreSQL, '?' за SQLite."""
    return "%s" if USE_POSTGRES else "?"


def _placeholders(n: int) -> str:
    ph = "%s" if USE_POSTGRES else "?"
    return ", ".join([ph] * n)


def _rows_to_dicts(rows) -> list:
    if not rows:
        return []
    return [dict(r) for r in rows]


AFFILIATE_FILE_FIELDS = (
    "logo_path",
    "logo_file",
    "logo",
    "document_path",
    "document_file",
    "file_path",
)


class AffiliateError(Exception):
    """Base class for affiliate-related domain errors."""


class AffiliateNotFoundError(AffiliateError):
    """Raised when affiliate does not exist."""


class DuplicateAffiliateEmailError(AffiliateError):
    """Raised when another affiliate already uses the requested email."""


class DuplicateAffiliatePromoCodeError(AffiliateError):
    """Raised when another affiliate already uses the requested promo code."""


def init_db() -> None:
    """Създава нужните таблици ако не съществуват."""
    pk = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS orders (
                id                {pk},
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
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS affiliates (
                id                 {pk},
                name               TEXT NOT NULL,
                email              TEXT NOT NULL UNIQUE,
                hashed_password    TEXT NOT NULL,
                promo_code         TEXT NOT NULL UNIQUE,
                commission_percent REAL NOT NULL,
                total_earned       REAL NOT NULL DEFAULT 0,
                total_paid         REAL NOT NULL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token        TEXT PRIMARY KEY,
                affiliate_id INTEGER NOT NULL,
                expires_at   TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()
    migrate_db()
    if USE_POSTGRES:
        print("[DB] ✅ База данни инициализирана: PostgreSQL")
    else:
        print(f"[DB] ✅ База данни инициализирана: {DB_PATH}")


def migrate_db() -> None:
    """Add new columns when they are missing."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if USE_POSTGRES:
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'orders'
            """)
            columns = {row["column_name"] for row in cursor.fetchall()}
            if not columns:
                # Table doesn't exist yet — skip migration
                return
        else:
            cursor.execute("PRAGMA table_info(orders)")
            columns = {row["name"] for row in cursor.fetchall()}

        if "esim_tran_no" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN esim_tran_no TEXT")
            conn.commit()
            print("[DB] ✅ Колона esim_tran_no добавена.")
        if "promo_code_used" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN promo_code_used TEXT")
            conn.commit()
            print("[DB] ✅ Колона promo_code_used добавена.")
        if "affiliate_commission" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN affiliate_commission REAL")
            conn.commit()
            print("[DB] ✅ Колона affiliate_commission добавена.")
        if "order_amount" not in columns:
            cursor.execute("ALTER TABLE orders ADD COLUMN order_amount REAL")
            conn.commit()
            print("[DB] ✅ Колона order_amount добавена.")
    finally:
        conn.close()


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
    params = (
        stripe_session_id, full_name, email, package_slug, country,
        gb, duration, iccid, esim_tran_no, qr_code_url, smdp_address,
        matching_id, lang, promo_code_used, affiliate_commission,
        order_amount, status, created_at,
    )
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if USE_POSTGRES:
            ph = _placeholders(len(params))
            cursor.execute(f"""
                INSERT INTO orders (
                    stripe_session_id, full_name, email, package_slug, country,
                    gb, duration, iccid, esim_tran_no, qr_code_url, smdp_address,
                    matching_id, lang, promo_code_used, affiliate_commission,
                    order_amount, status, created_at
                ) VALUES ({ph})
                ON CONFLICT (stripe_session_id) DO NOTHING
                RETURNING id
            """, params)
            conn.commit()
            result = cursor.fetchone()
            row_id = result["id"] if result else None
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO orders (
                    stripe_session_id, full_name, email, package_slug, country,
                    gb, duration, iccid, esim_tran_no, qr_code_url, smdp_address,
                    matching_id, lang, promo_code_used, affiliate_commission,
                    order_amount, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
            conn.commit()
            row_id = cursor.lastrowid
    finally:
        conn.close()

    print(f"[DB] ✅ Поръчка записана → id={row_id} | ICCID={iccid} | session={stripe_session_id[:20]}...")
    return row_id


def get_order_by_session(stripe_session_id: str) -> Optional[dict]:
    """Търси поръчка по Stripe session ID."""
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM orders WHERE stripe_session_id = {ph}",
            (stripe_session_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_order_by_iccid(iccid: str) -> Optional[dict]:
    """Find an order by ICCID."""
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM orders WHERE iccid = {ph}",
            (iccid,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_all_orders(status_filter: Optional[str] = None) -> List[dict]:
    """Връща всички поръчки, сортирани от най-новата."""
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if status_filter:
            cursor.execute(
                f"SELECT * FROM orders WHERE status = {ph} ORDER BY id DESC",
                (status_filter,),
            )
        else:
            cursor.execute("SELECT * FROM orders ORDER BY id DESC")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return _rows_to_dicts(rows)


def create_affiliate(
    name: str,
    email: str,
    hashed_password: str,
    promo_code: str,
    commission_percent: float,
    total_earned: float = 0.0,
    total_paid: float = 0.0,
) -> int:
    promo_code_clean = promo_code.strip().upper()
    if not 0 <= commission_percent <= 100:
        raise ValueError("commission_percent must be between 0 and 100")
    if not promo_code_clean or len(promo_code_clean) > 50:
        raise ValueError("promo_code must be between 1 and 50 characters")
    if not re.fullmatch(r"[A-Z0-9_-]+", promo_code_clean):
        raise ValueError("promo_code contains invalid characters")

    params = (
        name,
        email.strip().lower(),
        hashed_password,
        promo_code_clean,
        commission_percent,
        total_earned,
        total_paid,
    )
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if USE_POSTGRES:
            ph = _placeholders(len(params))
            cursor.execute(f"""
                INSERT INTO affiliates (
                    name, email, hashed_password, promo_code,
                    commission_percent, total_earned, total_paid
                ) VALUES ({ph})
                RETURNING id
            """, params)
            conn.commit()
            row_id = cursor.fetchone()["id"]
        else:
            cursor.execute("""
                INSERT INTO affiliates (
                    name, email, hashed_password, promo_code,
                    commission_percent, total_earned, total_paid
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, params)
            conn.commit()
            row_id = cursor.lastrowid
    finally:
        conn.close()
    return row_id


def get_affiliate_by_email(email: str) -> Optional[dict]:
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM affiliates WHERE lower(email) = lower({ph})",
            (email.strip(),),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_affiliate_by_id(affiliate_id: int) -> Optional[dict]:
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM affiliates WHERE id = {ph}",
            (affiliate_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_affiliate_by_promo_code(promo_code: str) -> Optional[dict]:
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM affiliates WHERE upper(promo_code) = upper({ph})",
            (promo_code.strip(),),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_all_affiliates() -> List[dict]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM affiliates ORDER BY id DESC")
        rows = cursor.fetchall()
    finally:
        conn.close()
    return _rows_to_dicts(rows)


def _validate_affiliate_inputs(email: str, promo_code: str, commission_percent: float) -> tuple[str, str]:
    """Validate and normalize affiliate form values.

    Returns `(email_clean, promo_code_clean)` after validating:
    - commission percent in inclusive range [0, 100]
    - email shape `local@domain.tld`
    - promo code format `[A-Z0-9_-]+` and length bounds
    """
    email_clean = email.strip().lower()
    promo_code_clean = promo_code.strip().upper()
    if not 0 <= commission_percent <= 100:
        raise ValueError("commission_percent must be between 0 and 100")
    if not email_clean or len(email_clean) > 255:
        raise ValueError("email must be between 1 and 255 characters")
    local_part, separator, domain_part = email_clean.partition("@")
    if (
        separator != "@"
        or not local_part
        or not domain_part
        or "." not in domain_part
        or domain_part.startswith(".")
        or domain_part.endswith(".")
        or ".." in domain_part
    ):
        raise ValueError("email is invalid")
    if not promo_code_clean or len(promo_code_clean) > 50:
        raise ValueError("promo_code must be between 1 and 50 characters")
    if not re.fullmatch(r"[A-Z0-9_-]+", promo_code_clean):
        raise ValueError("promo_code contains invalid characters")
    return email_clean, promo_code_clean


def update_affiliate(
    affiliate_id: int,
    name: str,
    email: str,
    promo_code: str,
    commission_percent: float,
) -> None:
    email_clean, promo_code_clean = _validate_affiliate_inputs(email, promo_code, commission_percent)
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT id FROM affiliates WHERE id = {ph}", (affiliate_id,))
        if not cursor.fetchone():
            raise AffiliateNotFoundError("affiliate_not_found")

        cursor.execute(
            f"SELECT id FROM affiliates WHERE lower(email) = lower({ph}) AND id <> {ph}",
            (email_clean, affiliate_id),
        )
        if cursor.fetchone():
            raise DuplicateAffiliateEmailError("email_already_exists")

        cursor.execute(
            f"SELECT id FROM affiliates WHERE upper(promo_code) = upper({ph}) AND id <> {ph}",
            (promo_code_clean, affiliate_id),
        )
        if cursor.fetchone():
            raise DuplicateAffiliatePromoCodeError("promo_code_already_exists")

        cursor.execute(
            f"""
            UPDATE affiliates
            SET name = {ph},
                email = {ph},
                promo_code = {ph},
                commission_percent = {ph}
            WHERE id = {ph}
            """,
            (name.strip(), email_clean, promo_code_clean, commission_percent, affiliate_id),
        )
        conn.commit()
    finally:
        conn.close()


def _safe_delete_affiliate_file(file_path: Optional[str]) -> None:
    """Delete an affiliate file only when it resolves inside the project directory."""
    if not file_path:
        return
    candidate = Path(file_path)
    base_dir = Path(__file__).resolve().parent.parent
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return
    try:
        resolved.relative_to(base_dir)
    except ValueError:
        return
    if resolved.exists() and resolved.is_file():
        resolved.unlink()


def delete_affiliate(affiliate_id: int) -> None:
    ph = _ph()
    conn = get_connection()
    affiliate_data = None
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM affiliates WHERE id = {ph}", (affiliate_id,))
        affiliate = cursor.fetchone()
        if not affiliate:
            raise AffiliateNotFoundError("affiliate_not_found")
        affiliate_data = dict(affiliate)

        cursor.execute(f"DELETE FROM affiliates WHERE id = {ph}", (affiliate_id,))
        conn.commit()
    finally:
        conn.close()

    affiliate_data = affiliate_data or {}
    file_paths = {
        file_path
        for field_name in AFFILIATE_FILE_FIELDS
        if (file_path := affiliate_data.get(field_name))
    }
    for file_path in file_paths:
        _safe_delete_affiliate_file(file_path)


def get_orders_by_promo_code(promo_code: str) -> List[dict]:
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT *
            FROM orders
            WHERE upper(COALESCE(promo_code_used, '')) = upper({ph})
            ORDER BY id DESC
            """,
            (promo_code.strip(),),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()
    return _rows_to_dicts(rows)


def update_affiliate_totals(
    affiliate_id: int,
    earned_delta: float = 0.0,
    paid_delta: float = 0.0,
) -> None:
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            UPDATE affiliates
            SET total_earned = total_earned + {ph},
                total_paid = total_paid + {ph}
            WHERE id = {ph}
            """,
            (earned_delta, paid_delta, affiliate_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_esim_tran_no_by_iccid(iccid: str) -> Optional[str]:
    """Return the esim_tran_no for an ICCID."""
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT esim_tran_no FROM orders WHERE iccid = {ph}",
            (iccid,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return row["esim_tran_no"] if row else None


def update_affiliate_password(affiliate_id: int, hashed_password: str) -> None:
    """Update the hashed password for an affiliate."""
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE affiliates SET hashed_password = {ph} WHERE id = {ph}",
            (hashed_password, affiliate_id),
        )
        conn.commit()
    finally:
        conn.close()


def create_password_reset_token(affiliate_id: int, token: str, expires_at: str) -> None:
    """Store a password reset token with its expiry."""
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"DELETE FROM password_reset_tokens WHERE affiliate_id = {ph}",
            (affiliate_id,),
        )
        cursor.execute(
            f"INSERT INTO password_reset_tokens (token, affiliate_id, expires_at) VALUES ({_placeholders(3)})",
            (token, affiliate_id, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_password_reset_token(token: str) -> Optional[dict]:
    """Return the reset token record or None if not found."""
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM password_reset_tokens WHERE token = {ph}",
            (token,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def delete_password_reset_token(token: str) -> None:
    """Delete a password reset token after use."""
    ph = _ph()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"DELETE FROM password_reset_tokens WHERE token = {ph}",
            (token,),
        )
        conn.commit()
    finally:
        conn.close()