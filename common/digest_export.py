# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def ensure_dir(path: str):
    if path and not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

def save_digest_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def mk_skeleton(vendor: str) -> Dict[str, Any]:
    return {
        "vendor": vendor,
        "timestamp_utc": now_utc_iso(),
        "counts": {
            "new_today": 0,
            "active": 0,
            "resolved_today": 0,
            "maintenance_today": 0,
        },
        "tables": {
            "today_rows_html": "",
            "past15_rows_html": "",
        },
        "sources": [],
    }

def extract_sources_from_module(mod) -> List[str]:
    """
    Heurística para obtener fuentes:
    - URL (str)
    - URLS (list)
    - SITES (list de dicts con 'url')
    """
    sources: List[str] = []
    if hasattr(mod, "URL") and isinstance(getattr(mod, "URL"), str):
        sources.append(mod.URL)
    if hasattr(mod, "URLS") and isinstance(getattr(mod, "URLS"), (list, tuple)):
        for u in getattr(mod, "URLS"):
            if isinstance(u, str):
                sources.append(u)
    if hasattr(mod, "SITES") and isinstance(getattr(mod, "SITES"), (list, tuple)):
        for s in getattr(mod, "SITES"):
            if isinstance(s, dict) and isinstance(s.get("url"), str):
                sources.append(s["url"])
    # dedup conservando orden
    out, seen = [], set()
    for s in sources:
        if s not in seen:
            out.append(s); seen.add(s)
    return out

def normalize_collect_style(vendor: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza salidas 'legacy' tipo:
      {"name": "...", "component_lines": [...], "incidents_lines": [...], "overall_ok": bool}
    a esquema digest estándar.
    """
    out = mk_skeleton(vendor)
    out["sources"] = raw.get("sources", []) or []
    comp = raw.get("component_lines") or []
    incs = raw.get("incidents_lines") or []

    # Conteo súper simple:
    active = 0
    resolved_today = 0
    maint = 0
    for line in incs:
        l = (line or "").lower()
        if any(k in l for k in ["investigating", "degraded", "outage", "partial"]):
            active += 1
        if "resolved" in l:
            resolved_today += 1
        if "maint" in l or "maintenance" in l:
            maint += 1

    out["counts"]["active"] = active
    out["counts"]["resolved_today"] = resolved_today
    out["counts"]["maintenance_today"] = maint

    # Filas HTML muy básicas (cada línea como 'estado' si no hay datos estructurados)
    today_rows = []
    for x in incs:
        if not x or "no incidents" in x.lower():
            continue
        today_rows.append(
            f"<tr><td>{vendor}</td><td>-</td><td>{escape_html(x)}</td>"
            f"<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
        )
    out["tables"]["today_rows_html"] = "\n".join(today_rows)
    # past15 lo dejamos vacío; si el vendor aporta datos, se populará desde collect real
    return out

def escape_html(s: str) -> str:
    return (s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"))

def export_with_fallback(mod, driver, vendor_name: str) -> Dict[str, Any]:
    """
    1) Si el módulo tiene collect(driver), lo usamos y normalizamos si es estilo-legacy.
    2) Si tiene export_for_digest(driver) y devuelve esquema ya normalizado, lo usamos.
    3) Fallback: devolvemos esqueleto con fuentes inferidas.
    """
    # 1) collect(driver)
    collector = getattr(mod, "collect", None)
    if callable(collector):
        raw = collector(driver)
        if isinstance(raw, dict) and ("component_lines" in raw or "incidents_lines" in raw):
            out = normalize_collect_style(vendor_name, raw)
            if not out["sources"]:
                out["sources"] = extract_sources_from_module(mod)
            return out
        # Si ya devuelve esquema estándar, lo respetamos:
        if isinstance(raw, dict) and "tables" in raw and "counts" in raw:
            return raw

    # 2) export_for_digest(driver)
    exp = getattr(mod, "export_for_digest", None)
    if callable(exp):
        raw = exp(driver)
        if isinstance(raw, dict) and "tables" in raw and "counts" in raw:
            if "vendor" not in raw:
                raw["vendor"] = vendor_name
            if "timestamp_utc" not in raw:
                raw["timestamp_utc"] = now_utc_iso()
            if not raw.get("sources"):
                raw["sources"] = extract_sources_from_module(mod)
            return raw

    # 3) Fallback mínimo
    out = mk_skeleton(vendor_name)
    out["sources"] = extract_sources_from_module(mod)
    return out
