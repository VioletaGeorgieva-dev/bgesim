import os
import json
import logging
from typing import Optional

from fastapi import FastAPI, Request, Form, Cookie, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.translations import get_ui
from app.database import (
    init_db,
    save_order,
    get_order_by_iccid,
    get_esim_tran_no_by_iccid,
    get_all_orders,
)
from app.api.client import (
    get_packages,
    order_esim,
    query_esim_usage,
    check_balance,
)

# Инициализация на FastAPI
app = FastAPI(title="BG eSIM", version="1.0.0")

# Статични файлове и шаблони
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

settings = get_settings()

@app.on_event("startup")
def startup_event():
    init_db()

def make_context(request: Request, lang: str, **extra):
    ui = get_ui(lang)
    ctx = {
        "request": request,
        "lang": lang,
        "ui": ui,
        "support_email": settings.SUPPORT_EMAIL,
    }
    ctx.update(extra)
    return ctx

@app.get("/", response_class=HTMLResponse)
def index_page(
    request: Request,
    lang: str = Cookie(default="en"),
):
    ctx = make_context(request, lang)
    return templates.TemplateResponse("index.html", ctx)

@app.get("/packages", response_class=HTMLResponse)
def packages_page(
    request: Request,
    location: Optional[str] = None,
    lang: str = Cookie(default="en"),
):
    try:
        packages_data = get_packages(location=location)
    except Exception as e:
        packages_data = {"error": str(e)}

    ctx = make_context(request, lang, packages_data=packages_data, location=location)
    return templates.TemplateResponse("packages.html", ctx)

@app.get("/checkout/{package_slug}", response_class=HTMLResponse)
def checkout_page(
    package_slug: str,
    request: Request,
    lang: str = Cookie(default="en"),
):
    ctx = make_context(request, lang, package_slug=package_slug)
    return templates.TemplateResponse("checkout.html", ctx)

@app.post("/checkout/{package_slug}")
def process_checkout(
    package_slug: str,
    email: str = Form(...),
    lang: str = Cookie(default="en"),
):
    try:
        res = order_esim(package_slug)
        iccid = res.get("iccid")
        qr_code_url = res.get("qr_code_url")
        raw_data = res.get("raw")

        esim_tran_no = None
        try:
            esim_tran_no = raw_data["obj"]["esimList"][0].get("esimTranNo")
        except (KeyError, IndexError):
            pass

        save_order(
            iccid=iccid,
            package_slug=package_slug,
            email=email,
            qr_code_url=qr_code_url,
            esim_tran_no=esim_tran_no,
        )

        return RedirectResponse(url=f"/success/{iccid}", status_code=303)
    except Exception as e:
        return HTMLResponse(content=f"<h3>Грешка при поръчката: {e}</h3>", status_code=400)

@app.get("/success/{iccid}", response_class=HTMLResponse)
def success_page(
    iccid: str,
    request: Request,
    lang: str = Cookie(default="en"),
):
    order = get_order_by_iccid(iccid)
    ctx = make_context(request, lang, iccid=iccid, order=order)
    return templates.TemplateResponse("success.html", ctx)

# -------------------------------------------------------------
# МАРШРУТ ЗА ПРОВЕРКА НА ПОТРЕБЛЕНИЕ (USAGE)
# -------------------------------------------------------------
@app.get("/usage/{iccid}", response_class=HTMLResponse)
def usage_page(
    request: Request,
    iccid: str,
    lang: str = Cookie(default="en"),
):
    usage_data = None
    error = None

    print(f"[USAGE PAGE] 📲 Отваряне на страница за ICCID: {iccid}")

    try:
        print(f"[USAGE PAGE] 🔄 Запитване към API за потребление...")
        usage_data = query_esim_usage(iccid=iccid, lang=lang)
        print(f"[USAGE PAGE] ✅ Получени данни: {usage_data}")

        if (
            usage_data
            and usage_data.get("not_active")
            and get_order_by_iccid(iccid)
            and not get_esim_tran_no_by_iccid(iccid)
        ):
            print(f"[USAGE PAGE] ⚠️ eSIM не е активиран, показване на наследствено съобщение")
            usage_data["remaining"] = get_ui(lang)["legacy_order_support"]
    except Exception as e:
        error = str(e)
        print(f"[USAGE PAGE] ❌ ГРЕШКА: {error}")

    ctx = make_context(
        request, lang,
        iccid=iccid,
        usage_data=usage_data,
        error=error,
    )
    return templates.TemplateResponse("usage.html", ctx)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
