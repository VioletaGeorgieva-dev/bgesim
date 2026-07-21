import urllib.parse
import requests
from app.config import get_settings
from app.translations import get_ui
import json

settings = get_settings()

BASE_URL = "https://api.esimaccess.com/api/v1/open"

HEADERS = {
    "RT-AccessCode": settings.esim_access_code,
    "Content-Type": "application/json",
    "Accept": "application/json",
}

def get_client() -> requests.Session:
    """Общ сесиен клиент с конфигурирани хедъри."""
    session = requests.Session()
    session.headers.update(HEADERS)
    return session

# ─────────────────────────────────────────────
# ПРОВЕРКА НА БАЛАНС
# ─────────────────────────────────────────────
def check_balance() -> dict:
    """Проверка на баланса"""
    client = get_client()
    response = client.post(f"{BASE_URL}/balance/query")
    response.raise_for_status()
    return response.json()

# ─────────────────────────────────────────────
# ЗАРЕЖДАНЕ НА ПАКЕТИ
# ─────────────────────────────────────────────
def get_packages(location: str = None) -> dict:
    """Вземи всички пакети, с опционален филтър по държава (напр. 'BG', 'DE')"""
    client = get_client()
    payload = {}
    if location:
        payload["locationCode"] = location
    response = client.post(f"{BASE_URL}/package/list", json=payload)
    response.raise_for_status()
    return response.json()

def get_package_by_slug(slug: str) -> dict:
    """Вземи конкретен пакет по slug"""
    client = get_client()
    payload = {"slug": slug}
    response = client.post(f"{BASE_URL}/package/list", json=payload)
    response.raise_for_status()
    return response.json()

# ─────────────────────────────────────────────
# КУПУВАНЕ НА eSIM — ОСНОВНА ФУНКЦИЯ
# ─────────────────────────────────────────────
def order_esim(package_slug: str) -> dict:
    """
    Купува eSIM пакет от доставчика (eSIM Access) и връща qr_code_url и iccid.
    """
    client = get_client()
    url = f"{BASE_URL}/esim/order"

    # Корекция: Пропускаме изцяло "price", за да не пращаме 'null' в JSON-а
    payload = {
        "packageInfoList": [
            {
                "packageCode": package_slug,
                "count": 1
            }
        ],
        "orderChannel": "api",
    }

    print(f"[eSIM Access] Изпращане на поръчка за пакет: {package_slug}")
    response = client.post(url, json=payload, timeout=15)
    response.raise_for_status()
    data = response.json()

    # Проверка за бизнес грешка от страна на eSIM Access
    if not data.get("success", False):
        error_code = data.get("errorCode", "UNKNOWN")
        error_msg  = data.get("errorMessage", "No message")
        raise ValueError(f"eSIM Access грешка [{error_code}]: {error_msg}")

    try:
        esim = data["obj"]["esimList"][0]
        iccid = esim.get("iccid", "")
        qr_code_url = esim.get("qrCodeUrl") or _ac_to_qr_url(esim.get("ac", ""))
    except (KeyError, IndexError) as e:
        raise ValueError(f"Неочаквана структура на отговора от доставчика: {e}\nRaw: {data}")

    return {
        "qr_code_url": qr_code_url,
        "iccid": iccid,
        "raw": data,
    }

# ─────────────────────────────────────────────
# ПОМОЩНА ФУНКЦИЯ — Activation Code → QR URL
# ─────────────────────────────────────────────
def _ac_to_qr_url(activation_code: str) -> str:
    """Генерира сигурен QR код линк, ако доставчикът върне само текстов код."""
    if not activation_code:
        return ""
    encoded = urllib.parse.quote(activation_code)
    return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded}"


def query_esim_usage(iccid_or_tran: str, lang: str = "en") -> dict:
    """
    Връща оставащите данни за даден ICCID или esim_tran_no.
    POST /esim/usage/query

    Поддържа множество формати на полета от API:
    - За обем: totalData, totalVolume, dataTotal, orderUsage
    - За използвано: dataUsage, usage, used
    - За оставащо: dataLeft, remainingData, leftData

    Приема или ICCID (начева с "89", дължина >= 18), или директно esim_tran_no.
    """
    from app.database import get_esim_tran_no_by_iccid

    ui = get_ui(lang)

    is_iccid = iccid_or_tran.startswith("89") and len(iccid_or_tran) >= 18

    if not is_iccid:
        # Подадената стойност вече е esim_tran_no – пропускаме базата и /esim/query
        print(f"[USAGE] ℹ️ Подадената стойност '{iccid_or_tran}' не изглежда като ICCID — третираме я като esim_tran_no")
        esim_tran_no = iccid_or_tran
    else:
        esim_tran_no = get_esim_tran_no_by_iccid(iccid_or_tran)

        if not esim_tran_no:
            print(f"[USAGE] ⚠️ ICCID {iccid_or_tran} – esim_tran_no не е намерен в базата, запитваме доставчика")
            try:
                client = get_client()
                query_response = client.post(
                    f"{BASE_URL}/esim/query",
                    json={"iccid": iccid_or_tran},
                    timeout=15,
                )
                query_response.raise_for_status()
                query_data = query_response.json()
            except requests.exceptions.RequestException as e:
                print(f"[USAGE] ❌ Грешка при запитване на esimTranNo от доставчика: {e}")
                query_data = {}

            if query_data.get("success"):
                obj = query_data.get("obj") or {}
                esim_list = obj.get("esimList") or []
                if esim_list:
                    esim_tran_no = esim_list[0].get("esimTranNo")

        if not esim_tran_no:
            print(f"[USAGE] ⚠️ ICCID {iccid_or_tran} – esim_tran_no не е намерен (вероятно не е активиран)")
            return {
                "total": ui["usage_pending_total"],
                "used": "0.00 GB",
                "remaining": ui["usage_pending_activation"],
                "percent": 0,
                "not_active": True,
            }

    url = f"{BASE_URL}/esim/usage/query"
    payload = {"esimTranNoList": [esim_tran_no]}

    print(f"[USAGE] 🔍 Запитване към eSIM Access за вход={iccid_or_tran}, esim_tran_no={esim_tran_no}")

    try:
        client = get_client()
        response = client.post(url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        print(f"[USAGE] ❌ Timeout при запитване")
        raise RuntimeError("[USAGE] ❌ Timeout — сървърът не отговори.")
    except requests.exceptions.RequestException as e:
        print(f"[USAGE] ❌ Мрежова грешка: {e}")
        raise RuntimeError(f"[USAGE] ❌ Мрежова грешка: {e}")

    # ЛОГВАНЕ НА СИРИЯ JSON ОТГОВОР
    print(f"[USAGE] 📊 Сиров отговор от eSIM Access: {json.dumps(data, indent=2)}")

    if not data.get("success"):
        err_msg = data.get('errorMsg', '') or data.get('errorMessage', 'Неизвестна грешка')
        print(f"[USAGE] ❌ API грешка: {err_msg}")
        raise ValueError(f"[USAGE] ❌ {err_msg}")

    usage_list = (data.get("obj") or {}).get("esimUsageList", [])
    if not usage_list:
        print(f"[USAGE] ⚠️ esimUsageList е празен за {iccid_or_tran}")
        return {
            "total": ui["usage_pending_total"],
            "used": "0.00 GB",
            "remaining": ui["usage_no_data"],
            "percent": 0,
            "not_active": True,
        }

    item = usage_list[0]
    print(f"[USAGE] 📋 Елемент от uso_list: {json.dumps(item, indent=2)}")

    # 🔍 ПРОВЕРКА НА ВСИЧКИ ВЪЗМОЖНИ ПОЛЕТА ЗА ОБЕМ
    total_bytes = (
        item.get("totalData") or 
        item.get("totalVolume") or 
        item.get("dataTotal") or 
        item.get("orderUsage") or 
        0
    )
    
    # 🔍 ПРОВЕРКА НА ВСИЧКИ ВЪЗМОЖНИ ПОЛЕТА ЗА ИЗПОЛЗВАНО
    used_bytes = (
        item.get("dataUsage") or 
        item.get("usage") or 
        item.get("used") or 
        0
    )
    
    # 🔍 ПРОВЕРКА НА ВСИЧКИ ВЪЗМОЖНИ ПОЛЕТА ЗА ОСТАВАЩО
    remaining_bytes = (
        item.get("dataLeft") or 
        item.get("remainingData") or 
        item.get("leftData") or 
        max(0, total_bytes - used_bytes)
    )

    print(f"[USAGE] 📐 Изчислени стойности:")
    print(f"       total_bytes={total_bytes}, used_bytes={used_bytes}, remaining_bytes={remaining_bytes}")

    def to_gb(b: int) -> str:
        if b == 0:
            return "0.00 GB"
        gb_value = b / (1024 ** 3)
        return f"{round(gb_value, 2)} GB"

    # ЗАЩИТА: ако total_bytes е 0 или отрицателен, вернем "не е активиран"
    if total_bytes <= 0:
        print(f"[USAGE] ⚠️ total_bytes = {total_bytes} (невалиден) — профилът може да не е активиран")
        return {
            "total": ui["usage_pending_total"],
            "used": "0.00 GB",
            "remaining": ui["usage_no_data"],
            "percent": 0,
            "not_active": True,
        }

    percent = round((used_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0

    result = {
        "total":     to_gb(total_bytes),
        "used":      to_gb(used_bytes),
        "remaining": to_gb(remaining_bytes),
        "percent":   percent,
        "not_active": False,
    }
    
    print(f"[USAGE] ✅ Успешно обработени данни: {result}")
    return result
