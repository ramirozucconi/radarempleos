"""Punto de entrada: baja todas las fuentes, filtra, puntúa y escribe data/."""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import sources as S
from .models import Job, parse_date
from .scoring import score_job

ROOT = Path(__file__).resolve().parent.parent


def build_tasks(cfg: dict) -> list[tuple[str, callable]]:
    src = cfg.get("sources", {})
    tasks = []
    for slug in src.get("greenhouse", {}).get("slugs", []):
        tasks.append((f"greenhouse:{slug}", lambda s=slug: S.collect_greenhouse(s)))
    for slug in src.get("ashby", {}).get("slugs", []):
        tasks.append((f"ashby:{slug}", lambda s=slug: S.collect_ashby(s)))
    for slug in src.get("lever", {}).get("slugs", []):
        tasks.append((f"lever:{slug}", lambda s=slug: S.collect_lever(s)))
    terms = src.get("workday_queries", {}).get("terms", [])
    for wd in src.get("workday", []):
        tasks.append((f"workday:{wd['tenant']}", lambda w=wd: S.collect_workday(w, terms)))
    for term in src.get("remotive", {}).get("searches", []):
        tasks.append((f"remotive:{term}", lambda t=term: S.collect_remotive(t)))
    for term in src.get("himalayas", {}).get("searches", []):
        tasks.append((f"himalayas:{term}", lambda t=term: S.collect_himalayas(t)))
    for term in src.get("getonbrd", {}).get("searches", []):
        tasks.append((f"getonbrd:{term}", lambda t=term: S.collect_getonbrd(t)))
    for feed in src.get("rss", {}).get("feeds", []):
        tasks.append((f"rss:{feed}", lambda f=feed: S.collect_rss(f)))
    return tasks


def collect(cfg: dict, workers: int = 8) -> tuple[list[Job], dict]:
    jobs: list[Job] = []
    report: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fn): name for name, fn in build_tasks(cfg)}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                got = fut.result()
                jobs += got
                report[name] = {"ok": True, "jobs": len(got)}
            except Exception as e:  # una fuente rota no frena al resto
                report[name] = {"ok": False, "error": str(e)[:300]}
    return jobs, report


def process(raw: list[Job], cfg: dict, seen: dict, now: datetime) -> tuple[list[dict], dict]:
    """Filtra, deduplica, marca nuevos y actualiza el estado `seen`."""
    stamp = now.isoformat(timespec="seconds")
    best: dict[str, Job] = {}
    for job in raw:
        scored = score_job(job, cfg, now)
        if scored and (scored.key not in best or scored.score > best[scored.key].score):
            best[scored.key] = scored

    out = []
    for key, job in best.items():
        entry = seen.setdefault(key, {"first_seen": stamp})
        entry["last_seen"] = stamp
        d = job.to_dict()
        d["first_seen"] = entry["first_seen"]
        d["is_new"] = entry["first_seen"] == stamp
        out.append(d)

    forget = now - timedelta(days=cfg.get("general", {}).get("forget_after_days", 60))
    for k in [k for k, v in seen.items() if (parse_date(v.get("last_seen")) or now) < forget]:
        del seen[k]

    out.sort(key=lambda d: (not d["is_new"], -d["score"]))
    return out[: cfg.get("general", {}).get("max_candidates", 200)], seen


def write_report(path: Path, jobs: list[dict], report: dict, now: datetime) -> None:
    ok = sum(1 for r in report.values() if r["ok"])
    lines = [
        f"# Radar de Empleos — {now:%Y-%m-%d %H:%M} UTC",
        "",
        f"Fuentes OK: {ok}/{len(report)} · Candidatos: {len(jobs)} · "
        f"Nuevos en esta corrida: {sum(j['is_new'] for j in jobs)}",
        "",
        "| Nuevo | Puntaje | Título | Empresa | Región | Ubicación |",
        "|---|---|---|---|---|---|",
    ]
    for j in jobs[:60]:
        lines.append(f"| {'✅' if j['is_new'] else ''} | {j['score']} | [{j['title']}]({j['url']}) | "
                     f"{j['company']} | {j['region']} | {j['location'][:40]} |")
    broken = sorted(k for k, r in report.items() if not r["ok"])
    if broken:
        lines += ["", "## Fuentes con error", ""] + [f"- `{b}`" for b in broken]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Recolector del Radar de Empleos")
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--data", default=str(ROOT / "data"))
    args = ap.parse_args(argv)

    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    data = Path(args.data)
    data.mkdir(parents=True, exist_ok=True)
    seen_path = data / "seen.json"
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}

    now = datetime.now(timezone.utc)
    raw, report = collect(cfg)
    jobs, seen = process(raw, cfg, seen, now)

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "stats": {"raw": len(raw), "candidates": len(jobs),
                  "new": sum(j["is_new"] for j in jobs),
                  "sources_ok": sum(r["ok"] for r in report.values()),
                  "sources_total": len(report)},
        "jobs": jobs,
    }
    (data / "candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    (data / "sources_report.json").write_text(json.dumps(dict(sorted(report.items())), indent=1), encoding="utf-8")
    seen_path.write_text(json.dumps(seen, indent=0), encoding="utf-8")
    write_report(data / "report.md", jobs, report, now)
    print(json.dumps(payload["stats"]))
    # Falla solo si TODAS las fuentes fallaron (algo grave: red caída, etc.)
    return 1 if report and not any(r["ok"] for r in report.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
