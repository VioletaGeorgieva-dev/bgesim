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
            print(f"[USAGE PAGE] ⚠️ eSIM не е активиран, показване на наследстве съобщение")
            usage_data["remaining"] = get_ui(lang)["legacy_order_support"]
    except Exception as e:
        error = str(e)
        print(f"[USAGE PAGE] ❌ ГРЕШКА: {error}")
        import traceback
        print(f"[USAGE PAGE] Traceback: {traceback.format_exc()}")

    ctx = make_context(
        request, lang,
        iccid=iccid,
        usage_data=usage_data,
        error=error,
    )
    return templates.TemplateResponse("usage.html", ctx)
