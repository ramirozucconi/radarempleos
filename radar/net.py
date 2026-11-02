"""Cliente HTTP mínimo (solo librería estándar) con reintentos."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; radar-empleos/1.0; +https://github.com)"


class FetchError(Exception):
    pass


def fetch(url: str, *, data: dict | None = None, timeout: int = 30,
          retries: int = 2, as_json: bool = True):
    body = json.dumps(data).encode() if data is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json, text/xml, */*"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if as_json else raw
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404, 410):
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise FetchError(f"{url}: {last}")
