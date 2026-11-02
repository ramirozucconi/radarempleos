"""Modelo común de aviso y utilidades de texto."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Job:
    source: str                 # p.ej. "greenhouse:stripe"
    company: str
    title: str
    url: str
    location: str = ""
    remote: bool | None = None
    posted_at: datetime | None = None
    description: str = ""
    salary: str = ""
    # Completados por el puntaje:
    score: int = 0
    region: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Clave estable para detectar el mismo aviso en distintas fuentes."""
        base = f"{norm(self.company)}|{norm(self.title)}|{norm(self.location)[:40]}"
        return hashlib.sha1(base.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        d["description"] = self.description[:1500]
        d["key"] = self.key
        return d


def norm(text: str) -> str:
    """Minúsculas, sin acentos, espacios simples."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


_TAG = re.compile(r"<[^>]+>")


def html_to_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)          # Greenhouse manda el HTML escapado
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value) -> datetime | None:
    """Acepta ISO 8601, epoch en segundos o milisegundos."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            n = float(value)
            if n > 1e12:
                n /= 1000
            return datetime.fromtimestamp(n, tz=timezone.utc)
        s = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
