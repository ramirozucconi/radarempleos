"""Filtros y puntaje: decide qué avisos le sirven a Rama y en qué orden."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .models import Job, norm


def _rx(*terms: str) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(terms) + r")\b")


# --- Títulos ---
CORE = _rx(
    r"procurement", r"purchas\w*", r"sourcing", r"procure.to.pay", r"ptp",
    r"accounts payable", r"vendor\w*", r"supplier\w*", r"contract (?:analyst|manag\w*|admin\w*|specialist)",
    r"billing", r"order.to.cash", r"o2c", r"revenue operations", r"rev ?ops",
    r"financ\w* operations", r"fin ?ops", r"payments? operations",
    r"business analyst", r"bi analyst", r"business intelligence", r"data analyst",
    r"sap", r"ariba", r"coupa", r"s/?4 ?hana",
    r"compras", r"comprador\w*", r"cuentas a pagar", r"abastecimiento", r"analista de datos",
)
ADJACENT = _rx(
    r"supply chain", r"fp&a", r"fp ?& ?a", r"financial analyst", r"finance analyst",
    r"financial systems", r"erp", r"operations analyst", r"business operations",
    r"strategy (?:&|and) operations", r"treasury", r"deal desk", r"sales operations",
    r"revenue analyst", r"accounting analyst", r"order management", r"operations associate",
    r"operations specialist", r"process analyst", r"analista (?:financier\w*|de operaciones|contable|de procesos)",
    r"finance (?:associate|specialist)",
)
EXCLUDE = _rx(
    r"account executive", r"sales development", r"business development rep\w*", r"sdr", r"bdr",
    r"account development", r"account manager", r"engineer\w*", r"developer", r"scientist",
    r"research\w*", r"designer", r"recruit\w*", r"intern", r"internship", r"pasant\w*",
    r"trainee", r"junior", r"jr", r"customer support", r"support (?:agent|specialist)",
    r"kyc", r"aml", r"fraud", r"compliance", r"counsel", r"paralegal", r"director", r"head of",
    r"vp", r"vice president", r"principal", r"staff", r"chief", r"architect",
    # Falsos positivos vistos en la primera corrida:
    r"client service\w*", r"customer service\w*", r"product manager", r"sales manager",
    r"people", r"hr", r"human resources", r"community", r"talent", r"trust",
    r"successfactors", r"servicenow", r"salesforce", r"m/w/d", r"w/m/d", r"\w*berater\w*",
)
SENIOR_PENALTY = _rx(r"manager", r"lead", r"gerente", r"jefe")

# --- Descripción: palabras que coinciden con el CV ---
CV_KEYWORDS = {
    r"sap": 6, r"ariba": 6, r"s/?4 ?hana": 4, r"procure.to.pay|p2p": 6, r"coupa": 4,
    r"purchase orders?|\bpos?\b": 3, r"invoice\w*|factura\w*": 4, r"vendor\w*|supplier\w*|proveedor\w*": 4,
    r"power bi": 6, r"sql": 5, r"snowflake": 4, r"power automate": 3, r"excel": 2,
    r"reconciliation|conciliaci\w*": 3, r"accounts payable|cuentas a pagar": 4,
    r"month.end|cierre": 2, r"dashboard\w*|tablero\w*": 2, r"procurement|compras": 4,
}
CV_KEYWORDS = {re.compile(r"\b(?:" + k + r")\b"): v for k, v in CV_KEYWORDS.items()}

# --- Ubicación ---
AR = _rx(r"argentina", r"buenos aires", r"caba", r"cordoba", r"rosario", r"mendoza")
LATAM = _rx(r"latam", r"latin america", r"latinoamerica", r"south america", r"sudamerica",
            r"americas", r"lac")
EU = _rx(
    r"europe", r"european union", r"\beu\b", r"emea", r"ireland", r"dublin", r"netherlands",
    r"amsterdam", r"germany", r"berlin", r"munich", r"france", r"paris", r"spain", r"madrid",
    r"barcelona", r"portugal", r"lisbon", r"italy", r"milan", r"rome", r"poland", r"warsaw",
    r"krakow", r"belgium", r"brussels", r"austria", r"vienna", r"sweden", r"stockholm",
    r"denmark", r"copenhagen", r"finland", r"helsinki", r"czech\w*", r"prague", r"hungary",
    r"budapest", r"romania", r"bucharest", r"greece", r"athens", r"luxembourg", r"estonia",
    r"tallinn", r"lithuania", r"vilnius", r"latvia", r"riga", r"croatia", r"slovenia",
    r"slovakia", r"bulgaria", r"sofia", r"cyprus", r"malta",
)
UK = _rx(r"united kingdom", r"uk", r"london", r"england", r"manchester", r"edinburgh", r"scotland")
GLOBAL = _rx(r"anywhere", r"worldwide", r"global", r"world")
DESC_OPEN_TO_US = _rx(r"argentina", r"latam", r"latin america", r"south america",
                      r"anywhere in the world", r"worldwide", r"fully remote from anywhere")
REMOTE_WORDS = re.compile(r"\b(remote|remoto|fully|full time|home office|work from home|wfh)\b|[^\w]+")


def classify_region(job: Job) -> tuple[str, int, list[str]]:
    """Devuelve (region, puntos, avisos). region == "" significa descartar."""
    loc = norm(job.location)
    desc = norm(job.description)
    if AR.search(loc):
        return "Argentina", 15, []
    if LATAM.search(loc):
        return "Latinoamérica", 12, []
    if EU.search(loc):
        return "Europa (UE)", 12, []
    if UK.search(loc):
        return "Reino Unido", 3, ["Requiere visa UK"]
    if GLOBAL.search(loc):
        return "Latinoamérica", 8, ["Remoto global: confirmar que acepta Argentina"]
    # "Remote" a secas o sin ubicación: solo si la descripción abre a LATAM/mundo.
    # Si la ubicación nombra cualquier otro lugar (US, Brasil, Bangladesh…), se descarta.
    leftover = REMOTE_WORDS.sub(" ", loc).strip(" ,;/-()|")
    if not leftover and DESC_OPEN_TO_US.search(desc):
        return "Latinoamérica", 6, ["Ubicación ambigua: confirmar que acepta Argentina"]
    return "", 0, []


def score_job(job: Job, cfg: dict, now: datetime | None = None) -> Job | None:
    """Aplica filtros duros; si pasa, completa score/region/flags y devuelve el aviso."""
    now = now or datetime.now(timezone.utc)
    g = cfg.get("general", {})
    title = norm(job.title)
    if not title or EXCLUDE.search(title):
        return None

    if CORE.search(title):
        pts = 40
    elif ADJACENT.search(title):
        pts = 22
    else:
        return None

    max_age = g.get("max_age_days", 30)
    if job.posted_at and job.posted_at < now - timedelta(days=max_age):
        return None

    region, rpts, flags = classify_region(job)
    if not region:
        return None
    pts += rpts

    desc = norm(job.description)
    pts += min(30, sum(w for rx, w in CV_KEYWORDS.items() if rx.search(desc)))

    if SENIOR_PENALTY.search(title):
        pts -= 8
        flags.append("Puede pedir más seniority")
    yrs = re.search(r"\b(8|9|10|12|15)\+?\s*(?:years|anos)", desc)
    if yrs:
        pts -= 15
        flags.append(f"Pide {yrs.group(1)}+ años")

    comp = norm(job.company)
    if any(p in comp for p in g.get("priority_companies", [])):
        pts += 10

    if job.posted_at and job.posted_at > now - timedelta(days=3):
        pts += 5

    job.score, job.region, job.flags = pts, region, flags
    return job if pts >= g.get("min_score", 35) else None
