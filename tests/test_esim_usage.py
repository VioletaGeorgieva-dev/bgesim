import os
import sqlite3
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("ESIM_ACCESS_CODE", "test-access-code")
os.environ.setdefault("ESIM_SECRET_KEY", "test-secret-key")
os.environ.setdefault("STRIPE_PUBLISHABLE_KEY", "pk_test")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("PARTNER_SESSION_SECRET", "test-partner-session-secret")
os.environ.setdefault("APP_ENV", "development")

from app import database
from app.api import client
from app import main
from app.translations import get_ui
from fastapi.testclient import TestClient


class DatabaseTests(unittest.TestCase):
    def test_init_db_migrates_existing_orders_table_and_creates_affiliates(self):
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

                database.init_db()

                with database.get_connection() as conn:
                    columns = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(orders)").fetchall()
                    }

                self.assertIn("esim_tran_no", columns)
                self.assertIn("promo_code_used", columns)
                self.assertIn("affiliate_commission", columns)
                self.assertIn("order_amount", columns)

                affiliate_tables = conn.execute("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'affiliates'
                """).fetchall()
                self.assertTrue(affiliate_tables)

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
                    promo_code_used="PARTNER10",
                    affiliate_commission=2.5,
                    order_amount=25.0,
                )

                order = database.get_order_by_iccid("8910")
                self.assertEqual(database.get_esim_tran_no_by_iccid("8910"), "TRAN123")
                self.assertEqual(order["stripe_session_id"], "sess_123")
                self.assertEqual(order["promo_code_used"], "PARTNER10")
                self.assertEqual(order["affiliate_commission"], 2.5)
                self.assertEqual(order["order_amount"], 25.0)


class AffiliateFlowTests(unittest.TestCase):
    def test_process_webhook_data_saves_affiliate_commission_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "orders.db"
            with patch.object(database, "DB_PATH", db_path):
                database.init_db()
                affiliate_id = database.create_affiliate(
                    name="Partner User",
                    email="partner@example.com",
                    hashed_password=main.PASSWORD_CONTEXT.hash("secret123"),
                    promo_code="PARTNER10",
                    commission_percent=10.0,
                )

                stripe_session = {
                    "metadata": {
                        "full_name": "Test Customer",
                        "package_slug": "gr_7days_1gb",
                        "country": "Greece",
                        "duration": "7",
                        "gb": "1",
                        "lang": "bg",
                        "promo_code_used": "PARTNER10",
                    },
                    "customer_email": "customer@example.com",
                    "amount_total": 2500,
                }
                event = {
                    "type": "checkout.session.completed",
                    "data": {"object": {"id": "cs_test_123"}},
                }

                with patch("app.main.stripe.checkout.Session.retrieve", return_value=stripe_session) as retrieve_mock:
                    with patch("app.main.order_esim", return_value={
                        "qr_code_url": "https://example.com/qr.png",
                        "iccid": "8910",
                        "esim_tran_no": "TRAN123",
                        "smdp_address": "SMDP",
                        "matching_id": "MATCH",
                        "lpa_string": "LPA:1$SMDP$MATCH",
                    }) as order_esim_mock:
                        with patch("app.utils.mailer.send_esim_email"):
                            with patch("app.utils.mailer.send_usage_email"):
                                main.process_webhook_data(event, "https://bgesim.bg/")
                                main.process_webhook_data(event, "https://bgesim.bg/")

                order_esim_mock.assert_called_once_with(package_code="gr_7days_1gb")
                retrieve_mock.assert_called_once_with("cs_test_123")
                order = database.get_order_by_iccid("8910")
                affiliate = database.get_affiliate_by_id(affiliate_id)
                self.assertEqual(len(database.get_orders_by_promo_code("PARTNER10")), 1)

                self.assertEqual(order["promo_code_used"], "PARTNER10")
                self.assertEqual(order["affiliate_commission"], 2.5)
                self.assertEqual(order["order_amount"], 25.0)
                self.assertEqual(affiliate["total_earned"], 2.5)

    def test_pay_adds_valid_promo_code_discount_to_checkout(self):
        client = TestClient(main.app, base_url="https://testserver")

        with patch("app.main.rate_limit", return_value=False):
            with patch("app.main.get_packages", return_value={
                "obj": {
                    "packageList": [
                        {"slug": "gr_7days_1gb", "price": 100000}
                    ]
                }
            }):
                with patch("app.main.stripe.PromotionCode.list", return_value={"data": [{"id": "promo_123"}]}) as promo_list_mock:
                    stripe_session = MagicMock()
                    stripe_session.url = "https://checkout.stripe.test/session"
                    with patch("app.main.stripe.checkout.Session.create", return_value=stripe_session) as create_session_mock:
                        response = client.post(
                            "/pay",
                            data={
                                "full_name": "Test User",
                                "email": "test@example.com",
                                "confirm_email": "test@example.com",
                                "package_slug": "gr_7days_1gb",
                                "country": "Greece",
                                "duration": "7",
                                "gb": "1",
                                "promo_code": "partner10",
                            },
                            follow_redirects=False,
                        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "https://checkout.stripe.test/session")
        promo_list_mock.assert_called_once_with(code="PARTNER10", active=True, limit=1)
        create_kwargs = create_session_mock.call_args.kwargs
        self.assertEqual(create_kwargs["discounts"], [{"promotion_code": "promo_123"}])
        self.assertEqual(create_kwargs["metadata"]["promo_code_used"], "PARTNER10")

    def test_partner_dashboard_hides_customer_personal_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "orders.db"
            with patch.object(database, "DB_PATH", db_path):
                database.init_db()
                database.create_affiliate(
                    name="Partner User",
                    email="partner@example.com",
                    hashed_password=main.PASSWORD_CONTEXT.hash("secret123"),
                    promo_code="PARTNER10",
                    commission_percent=10.0,
                    total_earned=2.5,
                )
                database.save_order(
                    stripe_session_id="sess_123",
                    full_name="Visible Customer",
                    email="visible@example.com",
                    package_slug="gr_7days_1gb",
                    country="Greece",
                    gb="1",
                    duration="7",
                    iccid="8910",
                    qr_code_url="https://example.com/qr.png",
                    promo_code_used="PARTNER10",
                    affiliate_commission=2.5,
                    order_amount=25.0,
                )

                client = TestClient(main.app, base_url="https://testserver")
                response = client.post(
                    "/partner/login",
                    data={"email": "partner@example.com", "password": "secret123"},
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn("Общо продажби", response.text)
                self.assertIn(">1<", response.text)
                self.assertIn("€2.50", response.text)
                self.assertIn("€25.00", response.text)
                self.assertNotIn("Visible Customer", response.text)
                self.assertNotIn("visible@example.com", response.text)


class AdminAffiliateTests(unittest.TestCase):
    def test_admin_affiliate_create_route_saves_affiliate_and_hashes_password(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "orders.db"
            with patch.object(database, "DB_PATH", db_path):
                database.init_db()
                client = TestClient(main.app, base_url="https://testserver")
                client.cookies.set("admin_auth", main.ADMIN_SESSION_VALUE)

                response = client.post(
                    "/admin/affiliates/create",
                    data={
                        "partner_name": "Michi Partner",
                        "partner_email": "partner@example.com",
                        "partner_password": "StrongPass123!",
                        "promo_code": "MICHI50",
                        "commission_percent": "12.5",
                    },
                    follow_redirects=True,
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn("Партньорът беше създаден успешно", response.text)
                self.assertIn("MICHI50", response.text)

                affiliate = database.get_affiliate_by_email("partner@example.com")
                self.assertIsNotNone(affiliate)
                self.assertNotEqual(affiliate["hashed_password"], "StrongPass123!")
                self.assertTrue(main.PASSWORD_CONTEXT.verify("StrongPass123!", affiliate["hashed_password"]))

    def test_admin_affiliate_create_requires_admin_auth(self):
        client = TestClient(main.app, base_url="https://testserver")
        response = client.post(
            "/admin/affiliates/create",
            data={
                "partner_name": "No Access",
                "partner_email": "noaccess@example.com",
                "partner_password": "StrongPass123!",
                "promo_code": "NOACCESS",
                "commission_percent": "10",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin")

    def test_admin_form_uses_partner_field_names_and_autocomplete(self):
        client = TestClient(main.app, base_url="https://testserver")
        client.cookies.set("admin_auth", main.ADMIN_SESSION_VALUE)

        response = client.get("/admin")

        class AdminCreateFormParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self._inside_create_form = False
                self.form_attrs = {}
                self.inputs_by_name = {}

            def handle_starttag(self, tag, attrs):
                attrs_dict = dict(attrs)
                if tag == "form" and attrs_dict.get("action") == "/admin/affiliates/create":
                    self._inside_create_form = True
                    self.form_attrs = attrs_dict
                    return
                if tag == "input" and self._inside_create_form and "name" in attrs_dict:
                    self.inputs_by_name[attrs_dict["name"]] = attrs_dict

            def handle_endtag(self, tag):
                if tag == "form" and self._inside_create_form:
                    self._inside_create_form = False

        parser = AdminCreateFormParser()
        parser.feed(response.text)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(parser.form_attrs.get("autocomplete"), "off")
        self.assertEqual(parser.inputs_by_name["partner_name"].get("autocomplete"), "off")
        self.assertEqual(parser.inputs_by_name["partner_email"].get("autocomplete"), "off")
        self.assertEqual(parser.inputs_by_name["partner_password"].get("autocomplete"), "new-password")


class QueryEsimUsageTests(unittest.TestCase):
    def test_query_esim_usage_returns_pending_when_transaction_number_missing(self):
        with patch("app.database.get_esim_tran_no_by_iccid", return_value=None):
            result = client.query_esim_usage("8910", lang="bg")

        self.assertTrue(result["not_active"])
        self.assertEqual(result["total"], get_ui("bg")["usage_pending_total"])
        self.assertEqual(result["remaining"], get_ui("bg")["usage_pending_activation"])

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
                result = client.query_esim_usage("8910", lang="en")

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
