"""Tests sin red: parsers con payloads de ejemplo + reglas de filtro/puntaje."""
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar import sources as S
from radar.main import process
from radar.models import Job
from radar.scoring import score_job

ROOT = Path(__file__).resolve().parent.parent
CFG = tomllib.loads((ROOT / "config.toml").read_text())
NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
RECENT = (NOW - timedelta(days=2)).isoformat()


def job(title, location="Argentina", company="Acme", desc="", posted=NOW - timedelta(days=2), remote=True):
    return Job(source="t", company=company, title=title, url="https://x/" + title,
               location=location, remote=remote, posted_at=posted, description=desc)


class Parsers(unittest.TestCase):
    def test_greenhouse(self):
        p = {"jobs": [{"title": "Procurement Analyst", "absolute_url": "https://g/1",
                       "location": {"name": "Dublin, IE"}, "first_published": RECENT,
                       "company_name": "Stripe", "content": "&lt;p&gt;SAP &amp; Ariba&lt;/p&gt;"}]}
        [j] = S.parse_greenhouse(p, "stripe")
        self.assertEqual((j.company, j.location, j.description), ("Stripe", "Dublin, IE", "SAP & Ariba"))
        self.assertIsNotNone(j.posted_at)

    def test_ashby(self):
        p = {"jobs": [{"title": "Billing Ops", "jobUrl": "https://a/1", "location": "London",
                       "secondaryLocations": [{"location": "Dublin"}], "isRemote": False,
                       "publishedAt": RECENT, "descriptionPlain": "SQL",
                       "compensation": {"compensationTierSummary": "€60K – €80K"}},
                      {"title": "Hidden", "isListed": False}]}
        [j] = S.parse_ashby(p, "kraken.com")
        self.assertEqual(j.location, "London, Dublin")
        self.assertEqual(j.salary, "€60K – €80K")
        self.assertEqual(j.company, "Kraken")

    def test_lever(self):
        p = [{"text": "Finance Operations Analyst", "hostedUrl": "https://l/1",
              "categories": {"location": "Buenos Aires", "allLocations": ["Buenos Aires", "Remote - LATAM"]},
              "workplaceType": "remote", "createdAt": 1793000000000, "descriptionPlain": "Power BI"}]
        [j] = S.parse_lever(p, "dlocal")
        self.assertEqual(j.location, "Buenos Aires, Remote - LATAM")
        self.assertTrue(j.remote)
        self.assertEqual(j.posted_at.year, 2026)

    def test_workday(self):
        cfg = {"host": "dow.wd1.myworkdayjobs.com", "tenant": "dow", "site": "ExternalCareers", "company": "Dow"}
        p = {"jobPostings": [{"title": "Buyer", "externalPath": "/job/BA/Buyer_R1",
                              "locationsText": "Buenos Aires", "postedOn": "Posted 3 Days Ago"}]}
        [j] = S.parse_workday(p, cfg, NOW)
        self.assertEqual(j.url, "https://dow.wd1.myworkdayjobs.com/ExternalCareers/job/BA/Buyer_R1")
        self.assertEqual((NOW - j.posted_at).days, 3)

    def test_remotive_himalayas_getonbrd(self):
        r = S.parse_remotive({"jobs": [{"title": "Data Analyst", "company_name": "X", "url": "u",
                                        "candidate_required_location": "LATAM", "publication_date": RECENT}]})
        h = S.parse_himalayas({"jobs": [{"title": "AP Analyst", "companyName": "Y", "applicationLink": "u",
                                         "locationRestrictions": ["Argentina", {"name": "Chile"}],
                                         "pubDate": 1793000000, "minSalary": 30000, "maxSalary": 40000}]})
        g = S.parse_getonbrd({"data": [{"id": "abc", "attributes": {
            "title": "Analista de Compras", "remote": True, "countries": ["Argentina"],
            "published_at": 1793000000, "company": {"data": {"attributes": {"name": "Z"}}}}}]})
        self.assertEqual(r[0].location, "LATAM")
        self.assertEqual(h[0].location, "Argentina, Chile")
        self.assertEqual((g[0].company, g[0].url), ("Z", "https://www.getonbrd.com/jobs/abc"))

    def test_rss(self):
        xml = """<rss><channel><item><title>Acme: Procurement Analyst</title><link>https://w/1</link>
                 <region>Anywhere in the World</region><pubDate>Mon, 02 Nov 2026 10:00:00 +0000</pubDate>
                 <description>&lt;b&gt;SAP&lt;/b&gt;</description></item></channel></rss>"""
        [j] = S.parse_rss(xml, "https://weworkremotely.com/remote-jobs.rss")
        self.assertEqual((j.company, j.title, j.description), ("Acme", "Procurement Analyst", "SAP"))


class Scoring(unittest.TestCase):
    def s(self, j):
        return score_job(j, CFG, NOW)

    def test_core_argentina_passes_high(self):
        j = self.s(job("Procurement Analyst", desc="SAP Ariba purchase orders invoices Power BI SQL"))
        self.assertEqual(j.region, "Argentina")
        self.assertGreaterEqual(j.score, 80)

    def test_rejects_sales_engineering_junior(self):
        for t in ["Account Executive", "Account Development Representative", "Software Engineer, Billing",
                  "Junior Data Analyst", "Procurement Intern", "KYC Operations Analyst"]:
            self.assertIsNone(self.s(job(t)), t)

    def test_rejects_unrelated_title(self):
        self.assertIsNone(self.s(job("Marketing Manager")))

    def test_location_rules(self):
        self.assertIsNone(self.s(job("Data Analyst", location="Brazil")))
        self.assertIsNone(self.s(job("Data Analyst", location="New York, NY")))
        self.assertIsNone(self.s(job("Data Analyst", location="Remote", desc="US only")))
        self.assertEqual(self.s(job("Billing Operations Analyst", location="Dublin, Ireland",
                                    company="Stripe")).region, "Europa (UE)")
        uk = self.s(job("Procurement Analyst", location="London, UK", company="Anthropic", desc="SAP sql"))
        self.assertIn("Requiere visa UK", uk.flags)
        amb = self.s(job("Procurement Analyst", location="Remote", desc="open to candidates in LATAM, SAP"))
        self.assertEqual(amb.region, "Latinoamérica")

    def test_old_posting_rejected_and_undated_kept(self):
        self.assertIsNone(self.s(job("Procurement Analyst", posted=NOW - timedelta(days=45))))
        self.assertIsNotNone(self.s(job("Procurement Analyst", posted=None, desc="SAP")))

    def test_experience_and_seniority_penalties(self):
        base = self.s(job("Procurement Analyst", desc="SAP sql"))
        senior = self.s(job("Procurement Analyst", desc="SAP sql 10+ years of experience"))
        self.assertTrue(senior is None or senior.score < base.score)

    def test_spanish_titles(self):
        self.assertIsNotNone(self.s(job("Analista de Compras Semi Senior", location="Buenos Aires", desc="SAP")))
        self.assertIsNotNone(self.s(job("Analista Cuentas a Pagar", location="CABA, Argentina", desc="SAP")))


class Pipeline(unittest.TestCase):
    def test_dedup_new_flag_and_forget(self):
        a = job("Procurement Analyst", company="Acme", desc="SAP")
        b = job("Procurement Analyst", company="ACME", desc="SAP Ariba Power BI sql")  # mismo aviso, mejor puntaje
        seen = {"old": {"first_seen": "2026-08-01T00:00:00+00:00", "last_seen": "2026-08-01T00:00:00+00:00"}}
        out, seen = process([a, b], CFG, seen, NOW)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["is_new"])
        self.assertNotIn("old", seen)
        out2, _ = process([a], CFG, seen, NOW + timedelta(hours=12))
        self.assertFalse(out2[0]["is_new"])


if __name__ == "__main__":
    unittest.main()
