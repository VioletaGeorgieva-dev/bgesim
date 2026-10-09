"""Send one data-usage warning per eSIM after 80% usage.

Run periodically from a Render Cron Job:
    python -m scripts.check_usage_alerts
"""
from __future__ import annotations

import os
from app.api.client import query_esim_usage
from app.database import USE_POSTGRES, get_connection, get_all_orders
from app.utils.mailer import send_usage_warning_email

THRESHOLD_PERCENT = float(os.getenv("USAGE_WARNING_THRESHOLD", "80"))
BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://bgesim.bg").rstrip("/")


def ensure_alert_table() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usage_alerts (
                iccid TEXT PRIMARY KEY,
                sent_at TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def claim_alert(iccid: str) -> bool:
    """Atomically reserve the one-time warning; callers release it if email fails."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO usage_alerts (iccid, sent_at) VALUES (%s, CURRENT_TIMESTAMP) "
                "ON CONFLICT (iccid) DO NOTHING RETURNING iccid",
                (iccid,),
            )
            claimed = cur.fetchone() is not None
        else:
            cur.execute(
                "INSERT OR IGNORE INTO usage_alerts (iccid, sent_at) "
                "VALUES (?, CURRENT_TIMESTAMP)",
                (iccid,),
            )
            claimed = cur.rowcount == 1
        conn.commit()
        return claimed
    finally:
        conn.close()


def release_alert(iccid: str) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        placeholder = "%s" if USE_POSTGRES else "?"
        cur.execute(f"DELETE FROM usage_alerts WHERE iccid = {placeholder}", (iccid,))
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    ensure_alert_table()
    orders = get_all_orders(status_filter="completed")
    for order in orders:
        iccid = str(order.get("iccid") or "").strip()
        if not iccid or not order.get("email"):
            continue
        try:
            usage = query_esim_usage(iccid_or_tran=iccid, lang=order.get("lang") or "en")
            if usage.get("not_active"):
                continue
            percent = float(usage.get("percent") or 0)
            if percent < THRESHOLD_PERCENT:
                continue
            if not claim_alert(iccid):
                continue
            try:
                send_usage_warning_email(
                    to_email=order["email"],
                    full_name=str(order.get("full_name") or ""),
                    country=str(order.get("country") or ""),
                    iccid=iccid,
                    topup_url=f"{BASE_URL}/topup/{iccid}",
                    percent_used=percent,
                    lang=str(order.get("lang") or "en"),
                )
                print(f"[USAGE ALERT] Sent {percent}% warning for order {order.get('id')}")
            except Exception:
                release_alert(iccid)
                raise
        except Exception as exc:
            print(f"[USAGE ALERT] Could not process order {order.get('id')}: {exc}")


if __name__ == "__main__":
    main()
