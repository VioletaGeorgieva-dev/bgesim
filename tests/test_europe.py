import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.europe import (
    EUROPE_PLANS,
    country_names,
    europe_text,
    plan_tagline,
    plan_title,
    process_plan_packages,
)
from app.translations import SUPPORTED_LANGS, get_ui

GB = 1024 ** 3


def pkg(slug, usd, gb, days, speed="4G/5G"):
    return {"slug": slug, "price": int(usd * 10000), "volume": int(gb * GB),
            "duration": days, "speed": speed, "name": slug}


SAMPLE = [
    pkg("EU-33_1_7", 0.64, 1, 7),
    pkg("EU-33_3_15", 1.69, 3, 15),
    pkg("EU-33_3_30", 1.80, 3, 30),
    pkg("EU-33_5_30", 2.82, 5, 30),
    pkg("EU-33_20_30", 11.29, 20, 30),
    pkg("EU-33_5_Daily", 3.00, 5, 1),          # дневен -> скрит
    pkg("EU-33_0.5_Daily", 1.00, 0.5, 1),      # дневен и под 1 GB -> скрит
    pkg("EU-33_5_30", 2.82, 5, 30),            # дубликат -> един път
    pkg("EU-30_5_30", 5.70, 5, 30),            # друг план -> скрит
]


class ProcessPlanPackagesTests(unittest.TestCase):
    def setUp(self):
        self.result = process_plan_packages(SAMPLE, "EU-33", 0.95, 2.0)

    def test_keeps_only_this_plan_without_daily_or_duplicates(self):
        self.assertEqual(
            [p["slug"] for p in self.result],
            ["EU-33_1_7", "EU-33_3_15", "EU-33_3_30", "EU-33_5_30", "EU-33_20_30"],
        )

    def test_price_uses_site_formula(self):
        prices = {p["slug"]: p["price_eur"] for p in self.result}
        self.assertEqual(prices["EU-33_1_7"], 1.22)
        self.assertEqual(prices["EU-33_5_30"], 5.36)
        self.assertEqual(prices["EU-33_20_30"], 21.45)

    def test_only_5gb_30_days_of_eu33_is_recommended(self):
        rec = [p["slug"] for p in self.result if p["recommended"]]
        self.assertEqual(rec, ["EU-33_5_30"])
        other = process_plan_packages(SAMPLE, "EU-30", 0.95, 2.0)
        self.assertFalse(any(p["recommended"] for p in other))

    def test_empty_input(self):
        self.assertEqual(process_plan_packages([], "EU-33", 0.95, 2.0), [])


class PlanConfigTests(unittest.TestCase):
    def test_country_counts_and_eu27_in_every_plan(self):
        counts = {p["code"]: len(p["countries"]) for p in EUROPE_PLANS}
        self.assertEqual(counts, {"EU-33": 33, "EU-30": 34, "EU-43": 41})
        for p in EUROPE_PLANS:
            self.assertEqual(len(set(p["countries"])), len(p["countries"]))
            for code in ("FR", "NL", "DE", "BG", "GR"):
                self.assertIn(code, p["countries"])

    def test_turkey_and_balkans_only_where_expected(self):
        by = {p["code"]: p["countries"] for p in EUROPE_PLANS}
        self.assertNotIn("TR", by["EU-33"])
        self.assertIn("TR", by["EU-30"])
        self.assertNotIn("RS", by["EU-30"])
        for code in ("RS", "MK", "MA", "TR"):
            self.assertIn(code, by["EU-43"])

    def test_text_fallback_to_english(self):
        self.assertEqual(europe_text("de"), europe_text("en"))
        self.assertNotEqual(europe_text("bg"), europe_text("en"))


class EuropeTemplateTests(unittest.TestCase):
    def render(self, lang, plans_packages):
        env = Environment(loader=FileSystemLoader(
            str(Path(__file__).resolve().parent.parent / "app" / "templates")))
        plans = []
        for plan in EUROPE_PLANS:
            plans.append({
                "code": plan["code"],
                "title": plan_title(plan, lang),
                "tagline": plan_tagline(plan, lang),
                "countries": plan["countries"],
                "country_names": country_names(plan, lang),
                "featured": plan["featured"],
                "packages": plans_packages.get(plan["code"], []),
            })
        prices = [p["price_eur"] for pk in plans_packages.values() for p in pk]
        return env.get_template("europe.html").render(
            lang=lang, t=get_ui(lang), supported_langs=SUPPORTED_LANGS,
            lang_urls={c: "/x" for c in SUPPORTED_LANGS},
            x=europe_text(lang), plans=plans,
            lowest_price=min(prices) if prices else None,
            highest_price=max(prices) if prices else None,
            offer_count=len(prices),
        )

    def test_renders_packages_checkout_links_and_seo(self):
        pk = {"EU-33": process_plan_packages(SAMPLE, "EU-33", 0.95, 2.0)}
        html = self.render("bg", pk)
        self.assertIn('rel="canonical" href="https://bgesim.bg/europe"', html)
        self.assertIn("checkout?package_slug=EU-33_5_30", html)
        self.assertIn("€5.36", html)
        self.assertIn("AggregateOffer", html)
        self.assertIn('"lowPrice": "1.22"', html)
        self.assertIn("Европа (33 държави)", html)
        self.assertIn("Нидерландия", html)

    def test_renders_without_packages(self):
        html = self.render("en", {})
        self.assertIn(europe_text("en")["unavailable"], html)
        self.assertNotIn("AggregateOffer", html)


if __name__ == "__main__":
    unittest.main()
