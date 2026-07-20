import unittest

from app.translations import get_password_reset_email


class PasswordResetEmailTranslationTests(unittest.TestCase):
    def test_get_password_reset_email_returns_localized_copy(self):
        reset_link = "https://example.com/partner/reset-password/token123"
        cases = {
            "bg": (
                "Нулиране на парола — BG eSIM",
                "🔑 Възстановяване на парола — BG eSIM",
                "Нулиране на парола →",
                "Ако не сте поискали това, просто игнорирайте имейла.",
            ),
            "en": (
                "Password Reset — BG eSIM",
                "🔑 Password Reset — BG eSIM",
                "Reset Password →",
                "If you did not request this, simply ignore this email.",
            ),
            "de": (
                "Passwort zurücksetzen — BG eSIM",
                "🔑 Passwort zurücksetzen — BG eSIM",
                "Passwort zurücksetzen →",
                "Wenn Sie dies nicht angefordert haben, ignorieren Sie diese E-Mail einfach.",
            ),
            "tr": (
                "Şifre Sıfırlama — BG eSIM",
                "🔑 Şifre Sıfırlama — BG eSIM",
                "Şifreyi Sıfırla →",
                "Bunu talep etmediyseniz, bu e-postayı görmezden gelin.",
            ),
            "es": (
                "Restablecer contraseña — BG eSIM",
                "🔑 Restablecer contraseña — BG eSIM",
                "Restablecer contraseña →",
                "Si no solicitaste esto, simplemente ignora este correo.",
            ),
        }

        for lang, (subject_text, title_text, button_text, footer_text) in cases.items():
            with self.subTest(lang=lang):
                subject, html_body = get_password_reset_email(lang, reset_link)
                self.assertEqual(subject, subject_text)
                self.assertIn(title_text, html_body)
                self.assertIn(button_text, html_body)
                self.assertIn(footer_text, html_body)
                self.assertIn(reset_link, html_body)
                self.assertIn("max-width:500px", html_body)
                self.assertIn("color:#1e40af", html_body)
                self.assertIn("background:#2563eb", html_body)
                self.assertIn("color:#6b7280; font-size:13px", html_body)

    def test_get_password_reset_email_falls_back_to_english(self):
        subject, html_body = get_password_reset_email("fr", "https://example.com/reset")

        self.assertEqual(subject, "Password Reset — BG eSIM")
        self.assertIn("🔑 Password Reset — BG eSIM", html_body)
        self.assertIn("Reset Password →", html_body)


if __name__ == "__main__":
    unittest.main()
