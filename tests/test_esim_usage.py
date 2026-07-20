import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("ESIM_ACCESS_CODE", "test-access-code")
os.environ.setdefault("ESIM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("STRIPE_PUBLISHABLE_KEY", "pk_test")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test")

from app import database
from app.api import client


class DatabaseTests(unittest.TestCase):
    def test_migrate_db_adds_esim_tran_no_to_existing_orders_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "legacy.db"
            with patch.object(database, "DB_PATH", db_path):
                with database.get_connection() as conn:
                    conn.execute("""
                        CREATE TABLE orders (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            stripe_session_id TEXT NOT NULL UNIQUE,
                            full_name TEXT,
                            email TEXT,
                            package_slug TEXT,
                            country TEXT,
                            gb TEXT,
                            duration TEXT,
                            iccid TEXT,
                            qr_code_url TEXT,
                            smdp_address TEXT,
                            matching_id TEXT,
                            lang TEXT,
                            status TEXT DEFAULT 'completed',
                            created_at TEXT NOT NULL
                        )
                    """)
                    conn.commit()

                database.migrate_db()

                with database.get_connection() as conn:
                    columns = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(orders)").fetchall()
                    }

                self.assertIn("esim_tran_no", columns)

    def test_save_order_persists_esim_tran_no(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "orders.db"
            with patch.object(database, "DB_PATH", db_path):
                database.init_db()
                database.save_order(
                    stripe_session_id="sess_123",
                    full_name="Test User",
                    email="test@example.com",
                    package_slug="bg_1gb",
                    country="BG",
                    gb="1",
                    duration="7",
                    iccid="8910",
                    qr_code_url="https://example.com/qr.png",
                    esim_tran_no="TRAN123",
                )

                self.assertEqual(
                    database.get_esim_tran_no_by_iccid("8910"),
                    "TRAN123",
                )
                self.assertEqual(
                    database.get_order_by_iccid("8910")["stripe_session_id"],
                    "sess_123",
                )


class QueryEsimUsageTests(unittest.TestCase):
    def test_query_esim_usage_returns_pending_when_transaction_number_missing(self):
        with patch("app.database.get_esim_tran_no_by_iccid", return_value=None):
            result = client.query_esim_usage("8910")

        self.assertTrue(result["not_active"])
        self.assertEqual(result["remaining"], "Пакетът изчаква активиране")

    def test_query_esim_usage_uses_esim_tran_no_payload_and_parses_usage_list(self):
        response = MagicMock()
        response.json.return_value = {
            "success": True,
            "obj": {
                "esimUsageList": [
                    {
                        "esimTranNo": "TRAN123",
                        "dataUsage": 536870912,
                        "totalData": 1073741824,
                    }
                ]
            },
        }
        response.raise_for_status.return_value = None

        session = MagicMock()
        session.post.return_value = response

        with patch("app.database.get_esim_tran_no_by_iccid", return_value="TRAN123"):
            with patch("app.api.client.get_client", return_value=session):
                result = client.query_esim_usage("8910")

        session.post.assert_called_once_with(
            "https://api.esimaccess.com/api/v1/open/esim/usage/query",
            json={"esimTranNoList": ["TRAN123"]},
            timeout=15,
        )
        self.assertEqual(result["total"], "1.0 GB")
        self.assertEqual(result["used"], "0.5 GB")
        self.assertEqual(result["remaining"], "0.5 GB")
        self.assertEqual(result["percent"], 50.0)
        self.assertFalse(result["not_active"])


if __name__ == "__main__":
    unittest.main()
