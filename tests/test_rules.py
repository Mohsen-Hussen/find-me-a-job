import unittest
from datetime import date

from jobhunt import rules, settings

S = settings.DEFAULTS


def screen(**overrides):
    base = {
        "relevant": True, "remote_type": "remote", "egypt_eligible": "yes", "eligibility_evidence": "",
        "company_hq": "", "engagement": "full-time", "pay_text": "", "pay_min_usd_year": None,
        "pay_max_usd_year": None, "tz_text": "", "tz_zone": "none", "tz_window_start": None,
        "tz_window_end": None, "tz_overlap_hours": None, "role_focus": "android", "seniority": "senior",
    }
    return {**base, **overrides}


def job(**screen_overrides):
    return {"prefilter": "ok", "closed": 0, "screen": screen(**screen_overrides)}


class Prefilter(unittest.TestCase):
    def test_titles(self):
        p = lambda t: rules.prefilter(t, S["search"])
        self.assertEqual(p("Senior Android Engineer"), "ok")
        self.assertEqual(p("Mobile Team Lead (Flutter)"), "ok")
        self.assertEqual(p("Software Engineer (Native SDKs)"), "ok")
        self.assertEqual(p("Senior iOS Developer"), "iOS-only title")
        self.assertEqual(p("iOS / Android Engineer"), "ok")
        self.assertIn("junior", p("Junior Android Developer"))
        self.assertEqual(p("Senior Backend Engineer"), "title is not a mobile role")


class Evaluate(unittest.TestCase):
    def test_match(self):
        self.assertEqual(rules.evaluate(job(), S)["status"], "match")

    def test_eligibility_floor(self):
        self.assertEqual(rules.evaluate(job(egypt_eligible="unclear"), S)["status"], "match")
        self.assertEqual(rules.evaluate(job(egypt_eligible="unlikely"), S)["status"], "excluded")
        self.assertEqual(rules.evaluate(job(egypt_eligible="no"), S)["status"], "excluded")

    def test_pay(self):
        self.assertEqual(rules.evaluate(job(pay_max_usd_year=90000), S)["status"], "excluded")
        self.assertEqual(rules.evaluate(job(pay_max_usd_year=150000), S)["status"], "match")
        flag = {**S, "fit": {**S["fit"], "below_min_pay": "flag"}}
        result = rules.evaluate(job(pay_max_usd_year=90000), flag)
        self.assertEqual(result["status"], "match")
        self.assertTrue(result["flags"])

    def test_engagement(self):
        self.assertEqual(rules.evaluate(job(engagement="part-time"), S)["status"], "excluded")
        self.assertEqual(rules.evaluate(job(engagement="unclear"), S)["status"], "match")

    def test_timezone_rule(self):
        self.assertEqual(rules.evaluate(job(tz_zone="America/Los_Angeles", tz_text="PST"), S)["status"], "excluded")
        self.assertEqual(rules.evaluate(job(tz_zone="America/New_York", tz_text="EST"), S)["status"], "match")


class Preferences(unittest.TestCase):
    def test_industries_and_companies(self):
        self.assertEqual(rules.evaluate(job(industries=["crypto", "fintech"]), S)["status"], "excluded")
        self.assertEqual(rules.evaluate(job(industries=["travel"]), S)["status"], "match")
        deed = {**job(), "company": "Deed"}
        self.assertEqual(rules.evaluate(deed, S)["status"], "excluded")
        indeed = {**job(), "company": "Indeed"}
        self.assertEqual(rules.evaluate(indeed, S)["status"], "match")


class RoleFocus(unittest.TestCase):
    def test_cross_platform_first_roles_dropped(self):
        self.assertEqual(rules.evaluate(job(role_focus="react-native"), S)["status"], "excluded")
        self.assertEqual(rules.evaluate(job(role_focus="flutter"), S)["status"], "excluded")
        self.assertEqual(rules.evaluate(job(role_focus="android"), S)["status"], "match")

    def test_titles(self):
        p = lambda t: rules.prefilter(t, S["search"], S["fit"])
        self.assertEqual(p("Senior Flutter Developer"), "Flutter-first title")
        self.assertEqual(p("React Native Engineer"), "React Native-first title")
        self.assertEqual(p("Senior Android Engineer (Kotlin, Flutter a plus)"), "ok")
        self.assertEqual(p("Senior Mobile Engineer"), "ok")


class Pay(unittest.TestCase):
    def test_parse(self):
        lo, hi = rules.pay_from_text("Up to EUR 20,000 per year, contractor")
        self.assertAlmostEqual(hi, 21600, delta=1)
        lo, hi = rules.pay_from_text("£85,000.00/yr - £100,000.00/yr")
        self.assertAlmostEqual(lo, 107950, delta=1)
        self.assertAlmostEqual(hi, 127000, delta=1)
        self.assertEqual(rules.pay_from_text("$60-80/hr"), (120000.0, 160000.0))
        self.assertEqual(rules.pay_from_text("$150k - $180k"), (150000.0, 180000.0))
        self.assertIsNone(rules.pay_from_text("Competitive Pay in USD"))
        self.assertIsNone(rules.pay_from_text("Based on experience"))

    def test_rule_uses_text_when_numbers_missing(self):
        self.assertEqual(rules.evaluate(job(pay_text="Gross annual salary range: €45,000–€65,000"), S)["status"], "excluded")
        self.assertEqual(rules.evaluate(job(pay_text="$140k-$170k"), S)["status"], "match")


class Timezone(unittest.TestCase):
    fit = S["fit"]

    def check(self, day, **s):
        return rules.timezone_check(screen(**s), self.fit, day)[0]

    def test_cairo_math_summer_and_winter(self):
        for day in (date(2026, 7, 1), date(2027, 1, 15)):
            self.assertEqual(self.check(day, tz_zone="America/New_York", tz_text="ET"), "yes")
            self.assertEqual(self.check(day, tz_zone="America/Los_Angeles", tz_text="PT"), "no")
            self.assertEqual(self.check(day, tz_zone="PT", tz_text="4h", tz_overlap_hours=4), "yes")
            self.assertEqual(self.check(day, tz_zone="Europe/Berlin", tz_text="CET"), "yes")
            self.assertEqual(self.check(day, tz_zone="unclear", tz_text="US-ish"), "unclear")


if __name__ == "__main__":
    unittest.main()
