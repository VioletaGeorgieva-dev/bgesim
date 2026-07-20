import requests
import uuid
from app.config import get_settings
from typing import Optional

settings = get_settings()

BASE_URL = "https://api.esimaccess.com/api/v1/open"

ESIM_ERROR_CODES = {
    "000001": "Грешка на сървъра.",
    "000101": "Липсва задължителен header.",
    "000102": "Грешен формат на header.",
    "000104": "Невалиден JSON формат.",
    "000105": "Липсват задължителни параметри.",
    "000106": "Задължителен параметър е null.",
    "101001": "Заявката е изтекла (timestamp).",
    "101002": "IP адресът е блокиран.",
    "101003": "Грешен подпис на заявката.",
    "200002": "Операцията не е разрешена при текущия статус.",
    "200005": "Грешна цена на пакета.",
    "200006": "Грешна обща сума на поръчката.",
    "200007": "Недостатъчен баланс по акаунта.",
    "200008": "Грешка в параметрите — свържете се с поддръжка.",
    "200009": "Анормален статус на поръчката.",
    "200010": "Профилът се изтегля в момента.",
    "200011": "Недостатъчно налични профили — свържете се с поддръжка.",
    "310241": "Невалиден packageCode.",
    "310243": "Пакетът не съществува.",
    "310272": "Номерът на поръчката не съществува.",
    "900001": "Системата е заета — опитайте отново.",
}


def _headers() -> dict:
    return {
        "RT-AccessCode": settings.esim_access_code,
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _check_response(data: dict, raw_text: str) -> None:
    success    = data.get("success", False)
    error_code = str(data.get("errorCode") or "").strip()
    error_msg  = data.get("errorMsg") or data.get("errorMessage") or "Няма съобщение."

    if success:
        return

    description = ESIM_ERROR_CODES.get(error_code, f"Непознат код: {error_code}")
    raise ValueError(
        f"[eSIM Access] ❌ Грешка!\n"
        f"  Код:       {error_code}\n"
        f"  Съобщение: {error_msg}\n"
        f"  Описание:  {description}\n"
        f"  Raw:       {raw_text[:300]}"
    )


def _parse_manual_install(ac: str) -> dict:
    """
    Извлича SM-DP+ Address и Matching ID от LPA низа.

    Вход:  "LPA:1$rsp-eu.redteamobile.com$451F9802E6854E3E85FB985235EDB4E5"
    Изход: {
        "lpa_string":   "LPA:1$rsp-eu.redteamobile.com$451F9802...",
        "smdp_address": "rsp-eu.redteamobile.com",
        "matching_id":  "451F9802E6854E3E85FB985235EDB4E5",
    }
    """
    if not ac or not ac.startswith("LPA:1$"):
        return {"lpa_string": ac, "smdp_address": "", "matching_id": ""}

    try:
        parts        = ac.split("$")
        smdp_address = parts[1] if len(parts) > 1 else ""
        matching_id  = parts[2] if len(parts) > 2 else ""
    except Exception:
        smdp_address = ""
        matching_id  = ""

    return {
        "lpa_string":   ac,
        "smdp_address": smdp_address,
        "matching_id":  matching_id,
    }


def order_esim(package_code: str) -> dict:
    order_url      = f"{BASE_URL}/esim/order"
    transaction_id = str(uuid.uuid4()).replace("-", "")[:50]

    payload = {
        "transactionId": transaction_id,
        "packageInfoList": [
            {
                "packageCode": package_code,
                "count": 1,
            }
        ],
    }

    print(f"[eSIM] → Поръчка: packageCode={package_code} | txn={transaction_id}")

    try:
        response = requests.post(order_url, headers=_headers(), json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        raise RuntimeError("[eSIM] ❌ Timeout при поръчка — сървърът не отговори.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"[eSIM] ❌ HTTP грешка при поръчка: {e} | {response.text[:200]}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"[eSIM] ❌ Мрежова грешка: {e}")
    except Exception:
        raise RuntimeError(f"[eSIM] ❌ Невалиден JSON отговор: {response.text[:200]}")

    print(f"[eSIM] ← Отговор от /esim/order: success={data.get('success')} | errorCode={data.get('errorCode')}")

    _check_response(data, response.text)

    order_no = data.get("obj", {}).get("orderNo", "")
    if not order_no:
        raise ValueError(f"[eSIM] ❌ Липсва orderNo в отговора: {data}")

    print(f"[eSIM] ✅ Поръчката е приета → orderNo={order_no}")

    return _query_esim_profile(order_no)


def _query_esim_profile(order_no: str, max_attempts: int = 10) -> dict:
    import time

    query_url = f"{BASE_URL}/esim/query"
    payload   = {
        "orderNo": order_no,
        "pager": {"pageNum": 1, "pageSize": 5},
    }

    print(f"[eSIM] ⏳ Изчакване на профила за orderNo={order_no}...")

    for attempt in range(1, max_attempts + 1):
        time.sleep(3)

        try:
            response = requests.post(query_url, headers=_headers(), json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"[eSIM] ⚠️ Опит {attempt}/{max_attempts} — грешка при query: {e}")
            continue

        error_code = str(data.get("errorCode") or "").strip()

        if error_code == "200010":
            print(f"[eSIM] ⏳ Опит {attempt}/{max_attempts} — профилът още се подготвя...")
            continue

        _check_response(data, response.text)

        try:
            esim_list = data["obj"]["esimList"]
            if not esim_list:
                print(f"[eSIM] ⏳ Опит {attempt}/{max_attempts} — esimList е празен...")
                continue

            esim        = esim_list[0]
            iccid       = esim.get("iccid", "")
            # Някои по-стари/алтернативни отговори връщат tran_no вместо esimTranNo.
            esim_tran_no = esim.get("esimTranNo", "") or esim.get("tran_no", "")
            qr_code_url = esim.get("qrCodeUrl", "")
            ac          = esim.get("ac", "")

            if not qr_code_url and ac:
                qr_code_url = _ac_to_qr_url(ac)

            if not iccid:
                print(f"[eSIM] ⏳ Опит {attempt}/{max_attempts} — iccid още не е готов...")
                continue

            # ── Извличане на данни за ръчно инсталиране ───
            manual = _parse_manual_install(ac)

            print(f"[eSIM] ✅ Профилът е готов → ICCID={iccid} | SM-DP+={manual['smdp_address']}")

            return {
                "qr_code_url":  qr_code_url,
                "iccid":        iccid,
                "esim_tran_no": esim_tran_no,
                "order_no":     order_no,
                "lpa_string":   manual["lpa_string"],    # LPA:1$...$...
                "smdp_address": manual["smdp_address"],  # rsp-eu.redteamobile.com
                "matching_id":  manual["matching_id"],   # 451F9802...
                "raw":          data,
            }

        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(f"[eSIM] ❌ Неочаквана структура: {e} | Raw: {data}")

    raise RuntimeError(
        f"[eSIM] ❌ Профилът не беше готов след {max_attempts} опита (~{max_attempts * 3} сек)."
        f" orderNo={order_no}"
    )


def _ac_to_qr_url(activation_code: str) -> str:
    import urllib.parse
    encoded = urllib.parse.quote(activation_code, safe="")
    return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded}"