"""Fuentes de avisos. Cada fuente tiene un parser puro (testeable sin red)
y un recolector que baja los datos y llama al parser."""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from .http import fetch
from .models import Job, html_to_text, parse_date

q = urllib.parse.quote_plus


# ---------------- Greenhouse ----------------
def parse_greenhouse(payload: dict, slug: str) -> list[Job]:
    jobs = []
    for j in payload.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        offices = ", ".join(o.get("name", "") for o in j.get("offices", []) or [])
        jobs.append(Job(
            source=f"greenhouse:{slug}",
            company=j.get("company_name") or slug,
            title=j.get("title", ""),
            url=j.get("absolute_url", ""),
            location=", ".join(x for x in (loc, offices) if x),
            remote="remote" in loc.lower() or None,
            posted_at=parse_date(j.get("first_published") or j.get("updated_at")),
            description=html_to_text(j.get("content")),
        ))
    return jobs


def collect_greenhouse(slug: str) -> list[Job]:
    data = fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    return parse_greenhouse(data, slug)


# ---------------- Ashby ----------------
def parse_ashby(payload: dict, slug: str, company: str | None = None) -> list[Job]:
    jobs = []
    for j in payload.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""]
        locs += [s.get("location", "") for s in j.get("secondaryLocations") or []]
        country = (((j.get("address") or {}).get("postalAddress") or {})
                   .get("addressCountry") or "")
        if country:
            locs.append(country)
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        jobs.append(Job(
            source=f"ashby:{slug}",
            company=company or slug.replace(".com", "").title(),
            title=j.get("title", ""),
            url=j.get("jobUrl") or j.get("applyUrl", ""),
            location=", ".join(dict.fromkeys(x for x in locs if x)),
            remote=j.get("isRemote") or (j.get("workplaceType") == "Remote") or None,
            posted_at=parse_date(j.get("publishedAt")),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            salary=comp,
        ))
    return jobs


def collect_ashby(slug: str) -> list[Job]:
    data = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    name = (data.get("organization") or {}).get("name") if isinstance(data, dict) else None
    return parse_ashby(data, slug, name)


# ---------------- Lever ----------------
def parse_lever(payload: list, slug: str) -> list[Job]:
    jobs = []
    for j in payload or []:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location") or ""]
        if j.get("country"):
            locs = list(locs) + [j["country"]]
        sr = j.get("salaryRange") or {}
        salary = ""
        if sr.get("min"):
            salary = f"{sr.get('currency', '')} {sr['min']}–{sr.get('max', '')} {sr.get('interval', '')}".strip()
        jobs.append(Job(
            source=f"lever:{slug}",
            company=slug,
            title=j.get("text", ""),
            url=j.get("hostedUrl", ""),
            location=", ".join(x for x in locs if x),
            remote=(j.get("workplaceType") == "remote") or None,
            posted_at=parse_date(j.get("createdAt")),
            description=j.get("descriptionPlain") or html_to_text(j.get("description")),
            salary=salary,
        ))
    return jobs


def collect_lever(slug: str) -> list[Job]:
    return parse_lever(fetch(f"https://api.lever.co/v0/postings/{slug}?mode=json"), slug)


# ---------------- Workday ----------------
_POSTED = re.compile(r"(\d+)\+?\s+day", re.I)


def workday_posted(text: str, now: datetime) -> datetime | None:
    t = (text or "").lower()
    if "today" in t or "hoy" in t:
        return now
    if "yesterday" in t or "ayer" in t:
        return now - timedelta(days=1)
    m = _POSTED.search(t)
    return now - timedelta(days=int(m.group(1))) if m else None


def parse_workday(payload: dict, cfg: dict, now: datetime) -> list[Job]:
    base = f"https://{cfg['host']}/{cfg['site']}"
    jobs = []
    for j in payload.get("jobPostings", []):
        jobs.append(Job(
            source=f"workday:{cfg['tenant']}",
            company=cfg["company"],
            title=j.get("title", ""),
            url=base + j.get("externalPath", ""),
            location=j.get("locationsText", ""),
            remote="remote" in (j.get("remoteType") or "").lower() or None,
            posted_at=workday_posted(j.get("postedOn", ""), now),
        ))
    return jobs


def collect_workday(cfg: dict, terms: list[str]) -> list[Job]:
    url = f"https://{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}/jobs"
    now = datetime.now(timezone.utc)
    out: list[Job] = []
    for term in terms:
        data = fetch(url, data={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term})
        out += parse_workday(data, cfg, now)
    return out


# ---------------- Remotive ----------------
def parse_remotive(payload: dict) -> list[Job]:
    return [Job(
        source="remotive",
        company=j.get("company_name", ""),
        title=j.get("title", ""),
        url=j.get("url", ""),
        location=j.get("candidate_required_location", ""),
        remote=True,
        posted_at=parse_date(j.get("publication_date")),
        description=html_to_text(j.get("description")),
        salary=j.get("salary") or "",
    ) for j in payload.get("jobs", [])]


def collect_remotive(search: str) -> list[Job]:
    return parse_remotive(fetch(f"https://remotive.com/api/remote-jobs?search={q(search)}&limit=100"))


# ---------------- Himalayas ----------------
def parse_himalayas(payload: dict) -> list[Job]:
    jobs = []
    for j in payload.get("jobs", []):
        restr = j.get("locationRestrictions") or []
        locs = [r if isinstance(r, str) else (r.get("name") or r.get("country") or "") for r in restr]
        salary = ""
        if j.get("minSalary"):
            salary = f"{j.get('currency', 'USD')} {j['minSalary']}–{j.get('maxSalary', '')} al año"
        jobs.append(Job(
            source="himalayas",
            company=j.get("companyName", ""),
            title=j.get("title", ""),
            url=j.get("applicationLink") or j.get("guid", ""),
            location=", ".join(locs) or "Worldwide",
            remote=True,
            posted_at=parse_date(j.get("pubDate")),
            description=html_to_text(j.get("description") or j.get("excerpt")),
            salary=salary,
        ))
    return jobs


def collect_himalayas(search: str) -> list[Job]:
    return parse_himalayas(fetch(f"https://himalayas.app/jobs/api/search?q={q(search)}&sort=recent"))


# ---------------- Get on Board ----------------
def parse_getonbrd(payload: dict) -> list[Job]:
    jobs = []
    for item in payload.get("data", []):
        a = item.get("attributes", {})
        comp = (((a.get("company") or {}).get("data") or {}).get("attributes") or {}).get("name", "")
        countries = a.get("countries") or []
        salary = ""
        if a.get("min_salary"):
            salary = f"USD {a['min_salary']}–{a.get('max_salary', '')} al mes"
        jobs.append(Job(
            source="getonbrd",
            company=comp,
            title=a.get("title", ""),
            url=(item.get("links") or {}).get("public_url") or f"https://www.getonbrd.com/jobs/{item.get('id', '')}",
            location=", ".join(countries) if countries else ("Remote" if a.get("remote") else ""),
            remote=bool(a.get("remote")),
            posted_at=parse_date(a.get("published_at")),
            description=html_to_text(" ".join(str(a.get(k) or "") for k in ("description", "functions", "desirable"))),
            salary=salary,
        ))
    return jobs


def collect_getonbrd(search: str) -> list[Job]:
    url = (f"https://www.getonbrd.com/api/v0/search/jobs?query={q(search)}"
           f"&per_page=50&expand=%5B%22company%22%5D")
    return parse_getonbrd(fetch(url))


# ---------------- RSS (We Work Remotely y similares) ----------------
def parse_rss(xml_text: str, feed: str) -> list[Job]:
    root = ET.fromstring(xml_text)
    jobs = []
    for it in root.iter("item"):
        title = it.findtext("title") or ""
        company, _, role = title.partition(":")
        if not role:
            company, role = "", title
        jobs.append(Job(
            source=f"rss:{urllib.parse.urlparse(feed).netloc}",
            company=company.strip(),
            title=role.strip(),
            url=it.findtext("link") or "",
            location=it.findtext("region") or "",
            remote=True,
            posted_at=_rss_date(it.findtext("pubDate")),
            description=html_to_text(it.findtext("description")),
        ))
    return jobs


def _rss_date(s: str | None) -> datetime | None:
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s) if s else None
    except (TypeError, ValueError):
        return None


def collect_rss(feed: str) -> list[Job]:
    return parse_rss(fetch(feed, as_json=False), feed)
