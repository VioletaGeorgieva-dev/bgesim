"""Регионални европейски планове от eSIM Access.

Пакетите се вземат на живо от API-то. Тук се пази само конфигурацията:
кои планове показваме, кои държави покриват и как се филтрират пакетите.
"""
import time
from typing import Any, Dict, List

from app.translations import translate_country

_EU27 = [
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
]

# Списъците с държави са преписани от таблицата на доставчика.
EUROPE_PLANS: List[Dict[str, Any]] = [
    {
        "code": "EU-33",
        "countries": _EU27 + ["GB", "CH", "NO", "IS", "LI", "GI"],
        "title": {"bg": "Европа (33 държави)", "en": "Europe (33 countries)"},
        "tagline": {
            "bg": "ЕС, Великобритания, Швейцария и Норвегия. Най-изгодният избор за Европа.",
            "en": "EU, UK, Switzerland and Norway. The best value for Europe.",
        },
        "featured": True,
    },
    {
        "code": "EU-30",
        "countries": _EU27 + ["GB", "CH", "NO", "IS", "LI", "UA", "TR"],
        "title": {"bg": "Европа + Турция и Украйна", "en": "Europe + Turkey & Ukraine"},
        "tagline": {
            "bg": "За маршрути, които минават през Турция или Украйна.",
            "en": "For trips that include Turkey or Ukraine.",
        },
        "featured": False,
    },
    {
        "code": "EU-43",
        "countries": _EU27 + [
            "GB", "CH", "NO", "IS", "LI", "UA", "TR",
            "RS", "MK", "MA", "GI", "IM", "AX", "JE",
        ],
        "title": {"bg": "Европа, Балкани и Мароко", "en": "Europe, Balkans & Morocco"},
        "tagline": {
            "bg": "Единственият план със Сърбия, Северна Македония и Мароко.",
            "en": "The only plan with Serbia, North Macedonia and Morocco.",
        },
        "featured": False,
    },
]


def plan_title(plan: Dict[str, Any], lang: str) -> str:
    return plan["title"].get(lang) or plan["title"]["en"]


def plan_tagline(plan: Dict[str, Any], lang: str) -> str:
    return plan["tagline"].get(lang) or plan["tagline"]["en"]


def country_names(plan: Dict[str, Any], lang: str) -> List[str]:
    return sorted(translate_country(code, lang) for code in plan["countries"])


def process_plan_packages(
    raw: List[Dict[str, Any]],
    plan_code: str,
    usd_to_eur: float,
    margin: float,
) -> List[Dict[str, Any]]:
    """Филтрира и подрежда пакетите на един регионален план.

    - взима само slug-ове от този план (защита, ако API-то върне повече);
    - маха дневните планове (duration == 1) и тези под 1 GB;
    - цената е със същата формула като в останалата част от сайта.
    """
    prefix = plan_code.upper() + "_"
    seen = set()
    result = []
    for p in raw:
        slug = p.get("slug", "")
        if not slug.upper().startswith(prefix) or slug.upper() in seen:
            continue
        seen.add(slug.upper())

        if p.get("duration", 0) == 1:
            continue
        volume_gb = round(p.get("volume", 0) / (1024 ** 3), 1)
        if volume_gb < 1:
            continue

        item = dict(p)
        item["volume_gb"] = volume_gb
        item["price_eur"] = round(p["price"] / 10000 * usd_to_eur * margin, 2)
        item["recommended"] = plan_code == "EU-33" and volume_gb == 5 and p.get("duration") == 30
        result.append(item)

    result.sort(key=lambda x: (x["duration"], x["volume_gb"]))
    return result


_cache: Dict[str, Any] = {}


def get_cached(key: str, loader, ttl: int = 3600):
    """Кеш в паметта. При грешка от API-то връща последния успешен резултат."""
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        value = loader()
    except Exception as exc:
        print(f"[EUROPE] ❌ Грешка при зареждане на {key}: {exc}")
        return hit[1] if hit else None
    _cache[key] = (now, value)
    return value


EUROPE_TEXT: Dict[str, Dict[str, Any]] = {
    "bg": {
        "page_title": "eSIM за Европа – 33 държави от €1.22 | BG eSIM",
        "meta_desc": "eSIM за цяла Европа с една карта: ЕС, Великобритания, Швейцария и Норвегия. Мобилен интернет без роуминг, инсталация с QR код за 2 минути.",
        "h1": "eSIM за Европа",
        "intro": "Една eSIM за цяла Европа. Инсталираш я със QR код за 2 минути и ползваш мобилен интернет без роуминг такси.",
        "covers": "Покрива {n} държави",
        "show": "Виж държавите",
        "from": "от",
        "recommended": "Препоръчан",
        "unavailable": "Пакетите временно не могат да се заредят. Опитайте отново след малко.",
        "note_title": "Добре е да знаете",
        "notes": [
            "Само мобилен интернет (data-only). Няма български номер за обаждания, но WhatsApp и Viber работят нормално.",
            "Валидността започва, когато се свържеш с мрежа в Европа.",
            "Ако ти трябват Турция, Сърбия, Северна Македония или Мароко, избери плана, който ги съдържа.",
        ],
    },
    "en": {
        "page_title": "Europe eSIM – 33 countries from €1.22 | BG eSIM",
        "meta_desc": "One eSIM for all of Europe: EU, UK, Switzerland and Norway. Mobile data without roaming fees, installed with a QR code in 2 minutes.",
        "h1": "Europe eSIM",
        "intro": "One eSIM for all of Europe. Install it with a QR code in 2 minutes and use mobile data without roaming fees.",
        "covers": "Covers {n} countries",
        "show": "Show countries",
        "from": "from",
        "recommended": "Recommended",
        "unavailable": "Plans are temporarily unavailable. Please try again in a moment.",
        "note_title": "Good to know",
        "notes": [
            "Data only. No phone number for calls, but WhatsApp and Viber work as usual.",
            "Validity starts when you connect to a network in Europe.",
            "If you need Turkey, Serbia, North Macedonia or Morocco, pick the plan that includes them.",
        ],
    },
}


def europe_text(lang: str) -> Dict[str, Any]:
    return EUROPE_TEXT.get(lang) or EUROPE_TEXT["en"]
