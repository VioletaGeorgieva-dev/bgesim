from collections import defaultdict
import time
from fastapi import FastAPI, Query, Request, Cookie, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.api.client import check_balance, get_packages, query_esim_usage
from app.services.esim import order_esim
from app.config import settings
from app.translations import (
    SUPPORTED_LANGS,
    translate_country,
    resolve_iso2_from_text,
    get_ui,
)
from app.database import init_db, save_order, get_all_orders
from pathlib import Path
from typing import Optional, List, Dict, Any
import urllib.parse
import uvicorn
import pycountry
import stripe
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

init_db()

stripe.api_key = settings.stripe_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="BG eSIM Portal")

USD_TO_EUR = 0.95
MARGIN_COEFFICIENT = 2.0

ADMIN_SESSION_VALUE = "authenticated_admin"


def get_server_side_price(package_slug: str) -> Optional[float]:
    """
    Взима официалната цена от eSIM Access API по package_slug.
    Никога не се доверява на цената от frontend-а.
    Връща price_eur или None ако пакетът не е намерен.
    """
    try:
        location_code = package_slug.split("_")[0]
        data = get_packages(location=location_code)
        packages = data.get("obj", {}).get("packageList", [])
        for p in packages:
            if p.get("slug", "").upper() == package_slug.upper():
                original_price_usd = p["price"] / 10000
                price_eur = round(original_price_usd * USD_TO_EUR * MARGIN_COEFFICIENT, 2)
                return price_eur
    except Exception as e:
        print(f"[PRICE CHECK] ❌ Грешка при вземане на цена за {package_slug}: {e}")
    return None


def process_webhook_data(event, base_url):
    """Тази функция обработва тежката логика на заден план, без да бави отговора към Stripe."""
    if event["type"] == "checkout.session.completed":
        raw_session = event["data"]["object"]
        session_id  = raw_session["id"]

        stripe_session = stripe.checkout.Session.retrieve(session_id)
        meta           = dict(stripe_session.get("metadata") or {})

        print(f"[BACKGROUND TASK] 🔍 Metadata: {meta}")

        if not meta.get("package_slug"):
            print("[BACKGROUND TASK] ⚠️ Липсва package_slug в metadata!")
            return

        package_slug   = meta.get("package_slug", "")
        full_name      = meta.get("full_name", "")
        country        = meta.get("country", "")
        duration       = meta.get("duration", "")
        gb             = meta.get("gb", "")
        lang           = meta.get("lang", "en")
        customer_email = stripe_session.get("customer_email", "")

        qr_code_url  = None
        iccid        = None
        smdp_address = ""
        matching_id  = ""
        lpa_string   = ""

        try:
            esim_result  = order_esim(package_code=package_slug)
            qr_code_url  = esim_result["qr_code_url"]
            iccid        = esim_result["iccid"]
            smdp_address = esim_result.get("smdp_address", "")
            matching_id  = esim_result.get("matching_id", "")
            lpa_string   = esim_result.get("lpa_string", "")
            print(f"[BACKGROUND TASK] ✅ eSIM купен: ICCID={iccid}")
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при купуване на eSIM: {e}")

        # 🍏🤖 ── СГЛОБЯВАНЕ НА UNIVERSAL LINKS (С МАЛКИ БУКВИ) ──
        
        ios_universal_link = ""
        android_universal_link = ""
        if lpa_string:
            # За Apple: Изискват изцяло малки букви, но оставяме символите $ и : чисти
            ios_universal_link = f"https://esimsetup.apple.com/esim_qrcode_provisioning?carddata={lpa_string.lower()}"
            
            # За Android: Подаваме АБСОЛЮТНО СУРОВИЯ низ (LPA:1$...), с големи букви и без кодиране
            android_universal_link = f"https://esimsetup.android.com/esim_qrcode_provisioning?carddata={lpa_string}"
        # ────────────────────────────────────────────────────────
        # ────────────────────────────────────────────────────────

        try:
            save_order(
                stripe_session_id = session_id,
                full_name         = full_name,
                email             = customer_email,
                package_slug      = package_slug,
                country           = country,
                gb                = gb,
                duration          = duration,
                iccid             = iccid or "",
                qr_code_url       = qr_code_url or "",
                smdp_address      = smdp_address,
                matching_id       = matching_id,
                lang              = lang,
                status            = "completed" if iccid else "esim_failed",
            )
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при запис в БД: {e}")

        try:
            from app.utils.mailer import send_esim_email
            send_esim_email(
                to_email     = customer_email,
                full_name    = full_name,
                country      = country,
                gb           = gb,
                duration     = duration,
                qr_code_url  = qr_code_url,
                iccid        = iccid,
                lang         = lang,
                smdp_address = smdp_address,
                matching_id  = matching_id,
                lpa_string   = lpa_string,
                ios_link     = ios_universal_link,      # 🍏 Нов параметър
                android_link = android_universal_link,  # 🤖 Нов параметър
            )
            print(f"[BACKGROUND TASK] 📧 Имейл 1 изпратен към: {customer_email}")
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при имейл 1: {e}")

        try:
            from app.utils.mailer import send_usage_email
            usage_url = base_url + f"usage/{iccid}"
            send_usage_email(
                to_email  = customer_email,
                full_name = full_name,
                country   = country,
                iccid     = iccid or "",
                usage_url = usage_url,
                lang      = lang,
            )
            print(f"[BACKGROUND TASK] 📧 Имейл 2 изпратен към: {customer_email}")
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при имейл 2: {e}")

        try:
            from app.utils.mailer import send_esim_email
            send_esim_email(
                to_email    = settings.SUPPORT_EMAIL,
                full_name   = f"🔔 НОВА ПОРЪЧКА от {full_name} ({customer_email})",
                country     = country,
                gb          = gb,
                duration    = duration,
                qr_code_url = qr_code_url,
                iccid       = iccid,
                lang        = "bg",
            )
            print(f"[BACKGROUND TASK] 📧 Admin известие изпратено към: {settings.SUPPORT_EMAIL}")
        except Exception as e:
            print(f"[BACKGROUND TASK] ❌ Грешка при admin известие: {e}")

    else:
        print(f"[BACKGROUND TASK] ℹ️ Игнорирано събитие: {event['type']}")


# ─── WEBHOOK ПЪРВО — преди всякакъв middleware! ───────────────────────────────
@app.post("/webhook")
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    print(f"[WEBHOOK] 📥 Получен! bytes={len(payload)}, sig={sig_header[:30]}")

    if not sig_header:
        print("[WEBHOOK] ❌ Липсва Stripe-Signature header!")
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature")

    if not payload:
        print("[WEBHOOK] ❌ Празен payload!")
        raise HTTPException(status_code=400, detail="Empty payload")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError as e:
        print(f"[WEBHOOK] ❌ Invalid payload: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")
    except stripe.SignatureVerificationError as e:
        print(f"[WEBHOOK] ❌ Invalid signature: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid signature: {e}")

    print(f"[WEBHOOK] ✅ Валидиран event: {event['type']}. Прехвърляне на заден план...")

    base_url = str(request.base_url)
    background_tasks.add_task(process_webhook_data, event, base_url)

    return {"status": "accepted"}
# ─────────────────────────────────────────────────────────────────────────────


# ─── MIDDLEWARE (след webhook!) ───────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"[REQUEST] {request.method} {request.url.path}")
    response = await call_next(request)
    print(f"[RESPONSE] {response.status_code}")
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
# ─────────────────────────────────────────────────────────────────────────────


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
templates.env.filters["urlencode"] = urllib.parse.quote
_request_counts: dict = defaultdict(list)


def rate_limit(ip: str, max_requests: int = 10, window: int = 60) -> bool:
    now = time.time()
    _request_counts[ip] = [
        t for t in _request_counts[ip]
        if now - t < window
    ]
    if len(_request_counts[ip]) >= max_requests:
        return True
    _request_counts[ip].append(now)
    return False


REGIONAL_KEYWORDS = {
    "europe", "asia", "africa",
    "north america", "south america", "latin america",
    "caribbean", "middle east", "oceania", "pacific",
    "balkans", "scandinavia", "nordic", "global",
}


def is_regional_package(name: str) -> bool:
    name_lower = name.lower()
    return any(keyword in name_lower for keyword in REGIONAL_KEYWORDS)


def resolve_country_code(query: str) -> Optional[str]:
    if not query:
        return None
    q = query.strip()
    found = resolve_iso2_from_text(q)
    if found:
        return found
    if len(q) <= 3:
        country = pycountry.countries.get(alpha_2=q.upper())
        if country:
            return country.alpha_2
        country = pycountry.countries.get(alpha_3=q.upper())
        if country:
            return country.alpha_2
    try:
        results = pycountry.countries.search_fuzzy(q)
        if results:
            return results[0].alpha_2
    except LookupError:
        pass
    return None


def process_packages(raw: List[Dict[Any, Any]], lang: str = "en") -> Dict[str, List]:
    seen = set()
    filtered = []

    for p in raw:
        name = p.get("name", "")
        slug = p.get("slug", "").lower()
        duration = p.get("duration", 0)

        if slug in seen:
            continue
        seen.add(slug)

        if duration == 1:
            continue

        volume_gb = round(p.get("volume", 0) / (1024 ** 3), 1)
        if volume_gb < 1:
            continue

        if "nonhkip" in slug or "nonhkip" in name.lower():
            continue

        if is_regional_package(name):
            continue

        original_price_usd = p["price"] / 10000
        p["price_eur"] = round(original_price_usd * USD_TO_EUR * MARGIN_COEFFICIENT, 2)

        location_code = p.get("locationCode", "")
        p["volume_gb"] = volume_gb
        p["country_name"] = translate_country(location_code, lang)

        filtered.append(p)

    groups: Dict[str, List] = {"7": [], "15": [], "30": [], "other": []}

    for p in filtered:
        d = p.get("duration", 0)
        if d == 7:
            groups["7"].append(p)
        elif d == 15:
            groups["15"].append(p)
        elif d == 30:
            groups["30"].append(p)
        else:
            groups["other"].append(p)

    for key in groups:
        groups[key].sort(key=lambda x: x["price_eur"])

    return groups


def make_lang_urls(request: Request, supported_langs: dict) -> dict:
    current_url = str(request.url.path)
    if request.query_params:
        current_url += "?" + str(request.query_params)
    lang_urls = {}
    for code in supported_langs:
        encoded = urllib.parse.quote(current_url, safe="")
        lang_urls[code] = f"/set-lang?lang={code}&redirect={encoded}"
    return lang_urls


def make_context(request: Request, lang: str, **kwargs) -> dict:
    return {
        "request": request,
        "lang": lang,
        "t": get_ui(lang),
        "supported_langs": SUPPORTED_LANGS,
        "lang_urls": make_lang_urls(request, SUPPORTED_LANGS),
        **kwargs,
    }


def get_country_suggestions(lang: str) -> list:
    from app.translations import COUNTRY_TRANSLATIONS
    result = []
    for iso2, names in COUNTRY_TRANSLATIONS.items():
        name = names.get(lang) or names.get("en") or iso2
        result.append((iso2, name))
    return sorted(result, key=lambda x: x[1])


@app.get("/set-lang")
def set_lang(lang: str = "en", redirect: str = "/"):
    valid = list(SUPPORTED_LANGS.keys())
    if lang not in valid:
        lang = "en"
    response = RedirectResponse(url=redirect)
    response.set_cookie(key="lang", value=lang, max_age=60*60*24*365)
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request, lang: str = Cookie(default="en")):
    ctx = make_context(
        request, lang,
        groups=None,
        selected_country="",
        resolved_code=None,
        error=None,
        total=0,
        country_suggestions=get_country_suggestions(lang),
    )
    return templates.TemplateResponse("index.html", ctx)


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    country: str = Query(""),
    lang: str = Cookie(default="en"),
):
    groups = None
    error = None
    resolved_code = None
    total = 0

    if country.strip():
        resolved_code = resolve_country_code(country.strip())
        if resolved_code:
            data = get_packages(location=resolved_code)
            raw_packages = data.get("obj", {}).get("packageList", [])
            groups = process_packages(raw_packages, lang=lang)
            total = sum(len(v) for v in groups.values())
        else:
            t = get_ui(lang)
            error = t["no_results"] + ": '" + country + "'"

    ctx = make_context(
        request, lang,
        groups=groups,
        selected_country=country,
        resolved_code=resolved_code,
        error=error,
        total=total,
        country_suggestions=get_country_suggestions(lang),
    )
    return templates.TemplateResponse("index.html", ctx)


@app.get("/instructions", response_class=HTMLResponse)
def instructions(request: Request, lang: str = Cookie(default="en")):
    ctx = make_context(request, lang)
    return templates.TemplateResponse("instructions.html", ctx)


@app.get("/contacts", response_class=HTMLResponse)
def contacts(request: Request, lang: str = Cookie(default="en")):
    ctx = make_context(
        request, lang,
        support_email=settings.SUPPORT_EMAIL,
        support_phone=settings.SUPPORT_PHONE,
    )
    return templates.TemplateResponse("contacts.html", ctx)


@app.get("/checkout", response_class=HTMLResponse)
def checkout(
    request: Request,
    package_slug: str = Query(""),
    country: str = Query(""),
    duration: int = Query(0),
    gb: float = Query(0.0),
    price_eur: float = Query(0.0),
    lang: str = Cookie(default="en"),
):
    ctx = make_context(
        request, lang,
        package_slug=package_slug,
        country=country,
        duration=duration,
        gb=gb,
        price_eur=price_eur,
    )
    return templates.TemplateResponse("checkout.html", ctx)


@app.get("/balance")
def balance():
    data = check_balance()
    balance_usd = data["obj"]["balance"] / 100
    return {
        "balance_cents": data["obj"]["balance"],
        "balance_usd": f"${balance_usd:.2f}"
    }


@app.post("/pay")
async def pay(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    confirm_email: str = Form(...),
    package_slug: str = Form(...),
    country: str = Form(...),
    duration: int = Form(...),
    gb: float = Form(...),
    lang: str = Cookie(default="en"),
):
    ip = request.client.host
    if rate_limit(ip, max_requests=5, window=60):
        raise HTTPException(status_code=429, detail="Твърде много заявки. Моля, изчакайте една минута.")

    # ── Проверка дали двата имейла съвпадат ──────────────────────────────────
    if email.strip().lower() != confirm_email.strip().lower():
        raise HTTPException(status_code=400, detail="Имейл адресите трябва да бъдат еднакви.")
    # ─────────────────────────────────────────────────────────────────────────

    # ── ЗАЩИТА: Цената се изчислява САМО от сървъра — frontend стойността се игнорира ──
    location_code = package_slug.split("_")[0]
    try:
        data = get_packages(location=location_code)
        packages = data.get("obj", {}).get("packageList", [])
    except Exception as e:
        print(f"[PAY] ❌ Грешка при извличане на пакети за {location_code}: {e}")
        raise HTTPException(status_code=503, detail="Временна грешка. Моля, опитайте отново.")

    server_price: Optional[float] = None
    for p in packages:
        if p.get("slug", "").upper() == package_slug.upper():
            original_price_usd = p["price"] / 10000
            server_price = round(original_price_usd * USD_TO_EUR * MARGIN_COEFFICIENT, 2)
            break

    if server_price is None:
        print(f"[PAY] ❌ Пакетът не е намерен: {package_slug}")
        raise HTTPException(status_code=400, detail="Невалиден пакет. Моля, опитайте отново.")

    amount_cents = int(round(server_price * 100))
    print(f"[PAY] ✅ Цена изчислена от сървъра: €{server_price} ({amount_cents} цента) за {package_slug}")
    # ─────────────────────────────────────────────────────────────────────────

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": amount_cents,
                "product_data": {
                    "name": f"eSIM {country} {gb}GB {duration} days",
                    "description": f"Package: {package_slug}",
                },
            },
            "quantity": 1,
        }],
        mode="payment",
        customer_email=email,
        metadata={
            "full_name":    full_name,
            "package_slug": package_slug,
            "country":      country,
            "duration":     str(duration),
            "gb":           str(gb),
            "lang":         lang,
        },
        success_url=str(request.base_url) + "success?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=str(request.base_url) + "cancel",
    )

    return RedirectResponse(url=session.url, status_code=303)


@app.get("/success", response_class=HTMLResponse)
def success(
    request: Request,
    session_id: str = Query(""),
    lang: str = Cookie(default="en"),
):
    ctx = make_context(request, lang, session_id=session_id)
    return templates.TemplateResponse("success.html", ctx)


@app.get("/cancel", response_class=HTMLResponse)
def cancel(request: Request, lang: str = Cookie(default="en")):
    ctx = make_context(request, lang)
    return templates.TemplateResponse("cancel.html", ctx)


@app.get("/test-email")
def test_email(secret: str = Query("")):
    if settings.APP_ENV != "development":
        raise HTTPException(status_code=404, detail="Not found")
    if secret != settings.test_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    from app.utils.mailer import send_esim_email
    send_esim_email(
        to_email    = "test@test.com",
        full_name   = "Test User",
        country     = "Germany",
        gb          = "3",
        duration    = "7",
        qr_code_url = "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=TestQR",
        iccid       = "89359999999999999",
        lang        = "bg",
    )
    return {"status": "✅ Имейлът е изпратен! Провери пощата."}


@app.get("/admin", response_class=HTMLResponse)
def admin_login(request: Request, lang: str = Cookie(default="en")):
    return templates.TemplateResponse("admin_login.html", {"request": request})


@app.post("/admin", response_class=HTMLResponse)
def admin_login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if (
        username != settings.ADMIN_USER or
        password != settings.ADMIN_PASSWORD
    ):
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Грешни данни!"},
            status_code=401,
        )
    # ── ЗАЩИТА: записваме фиксиран низ в бисквитката, НЕ паролата ────────────
    response = RedirectResponse(url="/admin/orders", status_code=303)
    response.set_cookie(
        key="admin_auth",
        value=ADMIN_SESSION_VALUE,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response
    # ─────────────────────────────────────────────────────────────────────────


@app.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(
    request: Request,
    admin_auth: str = Cookie(default=""),
    status_filter: str = Query(default="all"),
):
    # ── Проверяваме спрямо фиксирания низ, НЕ спрямо паролата ───────────────
    if admin_auth != ADMIN_SESSION_VALUE:
        return RedirectResponse(url="/admin", status_code=303)
    # ─────────────────────────────────────────────────────────────────────────

    orders = get_all_orders(status_filter=status_filter if status_filter != "all" else None)

    return templates.TemplateResponse("admin.html", {
        "request":       request,
        "orders":        orders,
        "status_filter": status_filter,
        "total":         len(orders),
    })


@app.get("/admin/logout")
def admin_logout():
    response = RedirectResponse(url="/admin", status_code=303)
    response.delete_cookie("admin_auth")
    return response


@app.get("/usage/{iccid}", response_class=HTMLResponse)
def usage_page(
    request: Request,
    iccid: str,
    lang: str = Cookie(default="en"),
):
    usage_data = None
    error      = None

    try:
        usage_data = query_esim_usage(iccid=iccid)
    except Exception as e:
        error = str(e)

    ctx = make_context(
        request, lang,
        iccid      = iccid,
        usage_data = usage_data,
        error      = error,
    )
    return templates.TemplateResponse("usage.html", ctx)


@app.get("/sitemap.xml")
def get_sitemap(request: Request):
    base_url = str(request.base_url).rstrip("/")

    urls = [
        f"{base_url}/",
        f"{base_url}/instructions",
        f"{base_url}/contacts",
        f"{base_url}/admin",
    ]

    sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'

    for url in urls:
        sitemap_xml += f"  <url>\n    <loc>{url}</loc>\n    <changefreq>daily</changefreq>\n  </url>\n"

    sitemap_xml += "</urlset>"

    return Response(content=sitemap_xml, media_type="application/xml")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
