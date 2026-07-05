import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import get_settings
from typing import Optional

settings = get_settings()
# ─────────────────────────────────────────────
# Преводи за Usage имейла
# ─────────────────────────────────────────────
USAGE_TRANSLATIONS = {
    "en": {
        "subject":    "Check your remaining data — {country} eSIM 📊",
        "header_sub": "Your eSIM is active",
        "greeting":   "Hello, {full_name}!",
        "body":       "Your eSIM for <strong>{country}</strong> is active and ready to use.",
        "iccid_label": "ICCID",
        "btn":        "Check Remaining Data →",
        "note":       "Data usage updates every 2–3 hours.",
        "footer":     "Questions?",
    },
    "bg": {
        "subject":    "Провери оставащите си данни — {country} eSIM 📊",
        "header_sub": "Вашият eSIM е активен",
        "greeting":   "Здравейте, {full_name}!",
        "body":       "Вашият eSIM за <strong>{country}</strong> е активен и готов за употреба.",
        "iccid_label": "ICCID",
        "btn":        "Провери оставащите данни →",
        "note":       "Потреблението се обновява на всеки 2–3 часа.",
        "footer":     "Въпроси?",
    },
    "de": {
        "subject":    "Überprüfen Sie Ihr verbleibendes Datenvolumen — {country} eSIM 📊",
        "header_sub": "Ihre eSIM ist aktiv",
        "greeting":   "Hallo, {full_name}!",
        "body":       "Ihre eSIM für <strong>{country}</strong> ist aktiv und einsatzbereit.",
        "iccid_label": "ICCID",
        "btn":        "Verbleibendes Datenvolumen prüfen →",
        "note":       "Die Datennutzung wird alle 2–3 Stunden aktualisiert.",
        "footer":     "Fragen?",
    },
    "tr": {
        "subject":    "Kalan verinizi kontrol edin — {country} eSIM 📊",
        "header_sub": "eSIM'iniz aktif",
        "greeting":   "Merhaba, {full_name}!",
        "body":       "<strong>{country}</strong> için eSIM'iniz aktif ve kullanıma hazır.",
        "iccid_label": "ICCID",
        "btn":        "Kalan Veriyi Kontrol Et →",
        "note":       "Veri kullanımı her 2–3 saatte bir güncellenir.",
        "footer":     "Sorularınız mı var?",
    },
    "es": {
        "subject":    "Consulta tus datos restantes — {country} eSIM 📊",
        "header_sub": "Tu eSIM está activa",
        "greeting":   "¡Hola, {full_name}!",
        "body":       "Tu eSIM para <strong>{country}</strong> está activa y lista para usar.",
        "iccid_label": "ICCID",
        "btn":        "Consultar datos restantes →",
        "note":       "El uso de datos se actualiza cada 2–3 horas.",
        "footer":     "¿Preguntas?",
    },
}


def send_usage_email(
    to_email: str,
    full_name: str,
    country: str,
    iccid: str,
    usage_url: str,
    lang: str = "en",
) -> None:
    u = USAGE_TRANSLATIONS.get(lang, USAGE_TRANSLATIONS["en"])

    if getattr(settings, "APP_ENV", "production") == "development" and settings.SUPPORT_EMAIL:
        recipient = settings.SUPPORT_EMAIL
        print(f"[USAGE EMAIL] ⚠️ Dev override: {to_email} → {recipient}")
    else:
        recipient = to_email

    subject = u["subject"].format(country=country)

    html_body = f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0; padding:0; background:#f3f4f6; font-family:Arial,sans-serif;">
      <div style="max-width:520px; margin:40px auto; background:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 4px 20px rgba(0,0,0,0.08);">
        <div style="background:linear-gradient(135deg,#2563eb,#1e40af); padding:32px 40px; text-align:center;">
          <h1 style="color:#ffffff; margin:0; font-size:24px;">📊 BG eSIM</h1>
          <p style="color:#bfdbfe; margin:8px 0 0; font-size:14px;">{u["header_sub"]}</p>
        </div>
        <div style="padding:32px 40px; text-align:center;">
          <p style="color:#1f2937; font-size:16px; margin-top:0; text-align:left;">{u["greeting"].format(full_name=full_name)}</p>
          <p style="color:#374151; font-size:15px; line-height:1.6; text-align:left;">{u["body"].format(country=country)}</p>
          <p style="color:#6b7280; font-size:13px; margin:16px 0 24px; text-align:left;">{u["iccid_label"]}: <strong style="color:#1f2937; font-family:monospace;">{iccid}</strong></p>
          <a href="{usage_url}" style="display:inline-block; background:#2563eb; color:#ffffff; font-size:16px; font-weight:bold; text-decoration:none; padding:16px 36px; border-radius:12px; margin:8px 0;">{u["btn"]}</a>
          <p style="color:#9ca3af; font-size:12px; margin-top:24px;">ℹ️ {u["note"]}</p>
        </div>
        <div style="background:#f9fafb; border-top:1px solid #e5e7eb; padding:20px 40px; text-align:center;">
          <p style="color:#9ca3af; font-size:12px; margin:0;">© 2025 BG eSIM · {u["footer"]} <a href="mailto:{settings.SUPPORT_EMAIL}" style="color:#2563eb;">{settings.SUPPORT_EMAIL}</a></p>
        </div>
      </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.smtp_sender_email
    msg["To"]      = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # Използваме стандартен SMTP с TLS порт 587, който работи безотказно в Render
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_server, 587, timeout=15) as server:
            server.starttls(context=context)
            server.login(settings.smtp_sender_email, settings.smtp_sender_password)
            server.sendmail(settings.smtp_sender_email, recipient, msg.as_string())
        print(f"[USAGE EMAIL] ✅ Изпратен към {recipient} (lang={lang})")
    except Exception as e:
        print(f"[USAGE EMAIL] ❌ Втори опит през порт 465 SSL поради грешка: {e}")
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_server, 465, context=context, timeout=15) as server:
            server.login(settings.smtp_sender_email, settings.smtp_sender_password)
            server.sendmail(settings.smtp_sender_email, recipient, msg.as_string())
        print(f"[USAGE EMAIL] ✅ Изпратен през архивен SSL порт към {recipient}")


EMAIL_TRANSLATIONS = {
    "en": {
        "subject":        "Your eSIM for {country} is ready! 🌐",
        "header_sub":     "Your eSIM is ready for activation",
        "greeting":       "Hello, {full_name}!",
        "thank_you":      "Thank you for your order. Your eSIM package is ready.",
        "col_country":    "🌍 Country",
        "col_data":       "📦 Data",
        "col_validity":   "📅 Validity",
        "col_days":       "{duration} days",
        "scan_qr":        "Scan the QR code with your phone:",
        "qr_pending":     "⚠️ The QR code will be sent shortly within a few minutes.",
        "iccid_label":    "ICCID",
        "manual_title":   "📲 Manual Installation (without QR code)",
        "manual_smdp":    "SM-DP+ Address",
        "manual_code":    "Activation Code",
        "how_to":         "📋 How to activate your eSIM:",
        "step1":          "Connect to <strong>Wi-Fi</strong>",
        "step2":          "Go to <strong>Settings → Mobile Data → Add eSIM</strong>",
        "step3":          "Scan the QR code above",
        "step4":          "Upon arrival, enable <strong>Data Roaming</strong>",
        "footer":         "Questions?",
    },
    "bg": {
        "subject":        "Вашият eSIM за {country} е готов! 🌐",
        "header_sub":     "Вашият eSIM е готов за активиране",
        "greeting":       "Здравейте, {full_name}!",
        "thank_you":      "Благодарим ви за поръчката. Вашият eSIM пакет е готов.",
        "col_country":    "🌍 Държава",
        "col_data":       "📦 Обем данни",
        "col_validity":   "📅 Валидност",
        "col_days":       "{duration} дни",
        "scan_qr":        "Сканирайте QR кода с телефона си:",
        "qr_pending":     "⚠️ QR кодът ще бъде изпратен допълнително в рамките на няколко минути.",
        "iccid_label":    "ICCID",
        "manual_title":   "📲 Ръчно инсталиране (без QR код)",
        "manual_smdp":    "SM-DP+ Адрес",
        "manual_code":    "Код за активиране",
        "how_to":         "📋 Как да активирате eSIM-а:",
        "step1":          "Свържете се с <strong>Wi-Fi</strong>",
        "step2":          "Отидете в <strong>Настройки → Мобилни данни → Добавяне на eSIM</strong>",
        "step3":          "Сканирайте QR кода по-горе",
        "step4":          "При пристигане включете <strong>Data Roaming</strong>",
        "footer":         "Въпроси?",
    },
    "de": {
        "subject":        "Ihre eSIM für {country} ist bereit! 🌐",
        "header_sub":     "Ihre eSIM ist zur Aktivierung bereit",
        "greeting":       "Hallo, {full_name}!",
        "thank_you":      "Vielen Dank für Ihre Bestellung. Ihr eSIM-Paket ist bereit.",
        "col_country":    "🌍 Land",
        "col_data":       "📦 Datenvolumen",
        "col_validity":   "📅 Gültigkeit",
        "col_days":       "{duration} Tage",
        "scan_qr":        "Scannen Sie den QR-Code mit Ihrem Telefon:",
        "qr_pending":     "⚠️ Der QR-Code wird in wenigen Minuten nachgesendet.",
        "iccid_label":    "ICCID",
        "manual_title":   "📲 Manuelle Installation (ohne QR-Code)",
        "manual_smdp":    "SM-DP+ Adresse",
        "manual_code":    "Aktivierungscode",
        "how_to":         "📋 So aktivieren Sie Ihre eSIM:",
        "step1":          "Verbinden Sie sich mit <strong>WLAN</strong>",
        "step2":          "Gehen Sie zu <strong>Einstellungen → Mobile Daten → eSIM hinzufügen</strong>",
        "step3":          "Scannen Sie den QR-Code oben",
        "step4":          "Aktivieren Sie beim Ankommen <strong>Daten-Roaming</strong>",
        "footer":         "Fragen?",
    },
    "tr": {
        "subject":        "{country} eSIM'iniz hazır! 🌐",
        "header_sub":     "eSIM'iniz etkinleştirmeye hazır",
        "greeting":       "Merhaba, {full_name}!",
        "thank_you":      "Siparişiniz için teşekkürler. eSIM paketiniz hazır.",
        "col_country":    "🌍 Ülke",
        "col_data":       "📦 Veri",
        "col_validity":   "📅 Geçerlilik",
        "col_days":       "{duration} gün",
        "scan_qr":        "Telefonunuzla QR kodunu tarayın:",
        "qr_pending":     "⚠️ QR kodu birkaç dakika içinde gönderilecektir.",
        "iccid_label":    "ICCID",
        "manual_title":   "📲 Manuel Kurulum (QR kodu olmadan)",
        "manual_smdp":    "SM-DP+ Adresi",
        "manual_code":    "Aktivasyon Kodu",
        "how_to":         "📋 eSIM'inizi nasıl etkinleştirirsiniz:",
        "step1":          "<strong>Wi-Fi</strong>'a bağlanın",
        "step2":          "<strong>Ayarlar → Mobil Veri → eSIM Ekle</strong> bölümüne gidin",
        "step3":          "Yukarıdaki QR kodunu tarayın",
        "step4":          "Varışta <strong>Veri Dolaşımı</strong>'nı etkinleştirin",
        "footer":         "Sorularınız mı var?",
    },
    "es": {
        "subject":        "¡Tu eSIM para {country} está lista! 🌐",
        "header_sub":     "Tu eSIM está lista para activarse",
        "greeting":       "¡Hola, {full_name}!",
        "thank_you":      "Gracias por tu pedido. Tu paquete eSIM está listo.",
        "col_country":    "🌍 País",
        "col_data":       "📦 Datos",
        "col_validity":   "📅 Validez",
        "col_days":       "{duration} días",
        "scan_qr":        "Escanea el código QR con tu teléfono:",
        "qr_pending":     "⚠️ El código QR se enviará en unos minutos.",
        "iccid_label":    "ICCID",
        "manual_title":   "📲 Instalación manual (sin código QR)",
        "manual_smdp":    "Dirección SM-DP+",
        "manual_code":    "Código de activación",
        "how_to":         "📋 Cómo activar tu eSIM:",
        "step1":          "Conéctate a <strong>Wi-Fi</strong>",
        "step2":          "Ve a <strong>Ajustes → Datos móviles → Añadir eSIM</strong>",
        "step3":          "Escanea el código QR de arriba",
        "step4":          "Al llegar, activa el <strong>Roaming de datos</strong>",
        "footer":         "¿Preguntas?",
    },
}


def _get_t(lang: str) -> dict:
    return EMAIL_TRANSLATIONS.get(lang, EMAIL_TRANSLATIONS["en"])


def send_esim_email(
    to_email: str,
    full_name: str,
    country: str,
    gb: str,
    duration: str,
    qr_code_url: Optional[str],
    iccid: Optional[str],
    lang: str = "en",
    smdp_address: str = "",
    matching_id:  str = "",
    lpa_string:   str = "",
) -> None:
    t = _get_t(lang)
    if getattr(settings, "APP_ENV", "production") == "development" and settings.SUPPORT_EMAIL:
        recipient = settings.SUPPORT_EMAIL
        print(f"[EMAIL] ⚠️ Development override: {to_email} → {recipient}")
    else:
        recipient = to_email

    print(f"[EMAIL] Изпращане към: {recipient} (lang={lang})")
    subject = t["subject"].format(country=country)

    if qr_code_url:
        qr_section = f"""
        <div style="text-align:center; margin:30px 0;">
            <p style="color:#374151; font-size:15px; margin-bottom:12px;">{t["scan_qr"]}</p>
            <img src="{qr_code_url}" alt="QR Code" width="220" style="border:4px solid #e5e7eb; border-radius:12px; padding:8px;">
        </div>
        """
    else:
        qr_section = f"""
        <div style="background:#fef3c7; border:1px solid #f59e0b; border-radius:8px; padding:12px; margin:20px 0; text-align:center;">{t["qr_pending"]}</div>
        """

    iccid_section = ""
    if iccid:
        iccid_section = f"""
        <p style="text-align:center; color:#6b7280; font-size:13px; margin-top:8px;">{t["iccid_label"]}: <strong style="color:#1f2937;">{iccid}</strong></p>
        """

    manual_section = ""
    if smdp_address and matching_id:
        manual_section = f"""
        <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:12px; padding:20px; margin-top:16px;">
            <p style="color:#374151; font-weight:bold; margin:0 0 12px; font-size:14px;">{t["manual_title"]}</p>
            <table style="width:100%; border-collapse:collapse; font-size:13px;">
                <tr style="border-bottom:1px solid #e5e7eb;">
                    <td style="color:#6b7280; padding:8px 0; width:45%;">{t["manual_smdp"]}</td>
                    <td style="color:#1f2937; font-weight:bold; padding:8px 0; font-family:monospace; word-break:break-all;">{smdp_address}</td>
                </tr>
                <tr>
                    <td style="color:#6b7280; padding:8px 0;">{t["manual_code"]}</td>
                    <td style="color:#1f2937; font-weight:bold; padding:8px 0; font-family:monospace; word-break:break-all;">{matching_id}</td>
                </tr>
            </table>
        </div>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html lang="{lang}">
    <head><meta charset="UTF-8"></head>
    <body style="margin:0; padding:0; background:#f3f4f6; font-family:Arial,sans-serif;">
      <div style="max-width:560px; margin:40px auto; background:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 4px 20px rgba(0,0,0,0.08);">
        <div style="background:linear-gradient(135deg,#2563eb,#1e40af); padding:32px 40px; text-align:center;">
          <h1 style="color:#ffffff; margin:0; font-size:24px;">🌐 BG eSIM</h1>
          <p style="color:#bfdbfe; margin:8px 0 0; font-size:14px;">{t["header_sub"]}</p>
        </div>
        <div style="padding:32px 40px;">
          <p style="color:#1f2937; font-size:16px; margin-top:0;">{t["greeting"].format(full_name=full_name)}</p>
          <p style="color:#374151; font-size:15px; line-height:1.6;">{t["thank_you"]}</p>
          <div style="background:#f9fafb; border:1px solid #e5e7eb; border-radius:12px; padding:20px; margin:24px 0;">
            <table style="width:100%; border-collapse:collapse;">
              <tr style="border-bottom:1px solid #e5e7eb;">
                <td style="color:#6b7280; font-size:14px; padding:10px 0;">{t["col_country"]}</td>
                <td style="color:#1f2937; font-weight:bold; font-size:14px; text-align:right; padding:10px 0;">{country}</td>
              </tr>
              <tr style="border-bottom:1px solid #e5e7eb;">
                <td style="color:#6b7280; font-size:14px; padding:10px 0;">{t["col_data"]}</td>
                <td style="color:#1f2937; font-weight:bold; font-size:14px; text-align:right; padding:10px 0;">{gb} GB</td>
              </tr>
              <tr>
                <td style="color:#6b7280; font-size:14px; padding:10px 0;">{t["col_validity"]}</td>
                <td style="color:#1f2937; font-weight:bold; font-size:14px; text-align:right; padding:10px 0;">{t["col_days"].format(duration=duration)}</td>
              </tr>
            </table>
          </div>
          {qr_section}
          {iccid_section}
          {manual_section}
          <div style="background:#eff6ff; border:1px solid #bfdbfe; border-radius:12px; padding:20px; margin-top:24px;">
            <p style="color:#1e40af; font-weight:bold; margin:0 0 12px;">{t["how_to"]}</p>
            <ol style="color:#374151; font-size:14px; line-height:1.8; margin:0; padding-left:20px;">
              <li>{t["step1"]}</li>
              <li>{t["step2"]}</li>
              <li>{t["step3"]}</li>
              <li>{t["step4"]}</li>
            </ol>
          </div>
        </div>
        <div style="background:#f9fafb; border-top:1px solid #e5e7eb; padding:20px 40px; text-align:center;">
          <p style="color:#9ca3af; font-size:12px; margin:0;">© 2025 BG eSIM · {t["footer"]} <a href="mailto:{settings.SUPPORT_EMAIL}" style="color:#2563eb;">{settings.SUPPORT_EMAIL}</a></p>
        </div>
      </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.smtp_sender_email
    msg["To"]      = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # Интелигентно тестване през порт 587 (с TLS) и автоматичен бекъп към 465 (SSL)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_server, 587, timeout=15) as server:
            server.starttls(context=context)
            server.login(settings.smtp_sender_email, settings.smtp_sender_password)
            server.sendmail(settings.smtp_sender_email, recipient, msg.as_string())
        print(f"[EMAIL] ✅ Изпратен успешно през TLS порт 587 към {recipient}")
    except Exception as e:
        print(f"[EMAIL] ❌ Грешка през TLS, опит през SSL порт 465: {e}")
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_server, 465, context=context, timeout=15) as server:
            server.login(settings.smtp_sender_email, settings.smtp_sender_password)
            server.sendmail(settings.smtp_sender_email, recipient, msg.as_string())
        print(f"[EMAIL] ✅ Изпратен успешно през SSL порт 465 към {recipient}")
