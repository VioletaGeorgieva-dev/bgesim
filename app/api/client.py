import urllib.parse
import requests
from app.config import get_settings

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


def query_esim_usage(iccid: str) -> dict:
    """
    Връща оставащите данни за даден ICCID.
    POST /esim/usage/query
    """
    url     = f"{BASE_URL}/esim/usage/query"
    payload = {"iccid": iccid}

    try:
        client   = get_client()
        response = client.post(url, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        raise RuntimeError("[USAGE] ❌ Timeout — сървърът не отговори.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"[USAGE] ❌ Мрежова грешка: {e}")

    # ─── 🛡️ ТУК Е ЗАЩИТАТА СРЕЩУ ПРАЗНИ ТРАНЗАКЦИИ (esimTranNoList) ───
    if not data.get("success"):
        err_msg = data.get('errorMsg', '') or data.get('errorMessage', 'Неизвестна грешка')
        
        # Проверяваме дали грешката е заради липса на активирана сесия/транзакция
        if "esimtrannolist" in err_msg.lower() or "must not be null" in err_msg.lower():
            # Връщаме празен/подготвен статус, вместо да хвърляме изключение (гърмим)
            return {
                "total": "В процес...",
                "used": "0.00 GB",
                "remaining": "Пакетът изчаква активиране",
                "percent": 0,
                "not_active": True  # Флаг, който да ни каже, че картата още не е стартирана
            }
        
        raise ValueError(f"[USAGE] ❌ {err_msg}")
    # ─────────────────────────────────────────────────────────────────

    obj = data.get("obj") or {}

    total_bytes = obj.get("totalVolume", 0)
    # FIX: Правилното поле е 'usageVolume', не 'orderUsage'
    # 'orderUsage' не се връща от /esim/usage/query — резултатът беше винаги 0
    used_bytes  = obj.get("usageVolume", 0)
    remaining   = max(0, total_bytes - used_bytes)

    def to_gb(b: int) -> str:
        return f"{round(b / (1024 ** 3), 2)} GB"

    percent = round((used_bytes / total_bytes * 100), 1) if total_bytes > 0 else 0

    return {
        "total":     to_gb(total_bytes),
        "used":      to_gb(used_bytes),
        "remaining": to_gb(remaining),
        "percent":   percent,
        "not_active": False
    }
