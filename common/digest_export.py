# common/digest_export.py
# -*- coding: utf-8 -*-
import os, json
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
        "counts": {"new_today": 0, "active": 0, "resolved_today": 0, "maintenance_today": 0},
        "tables": {"today_rows_html": "", "past15_rows_html": ""},
        "sources": [],
    }

def extract_sources_from_module(mod) -> List[str]:
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
    out, seen = [], set()
    for s in sources:
        if s not in seen:
            out.append(s); seen.add(s)
    return out

def escape_html(s: str) -> str:
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _read_capture(vendor: str) -> str | None:
    out_dir = os.getenv("DIGEST_OUT_DIR", ".github/out/vendors")
    path = os.path.join(out_dir, f"{vendor}.capture.txt")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
    return None

def _build_from_capture(vendor: str, capture_text: str) -> Dict[str, Any]:
    data = mk_skeleton(vendor)
    if not capture_text:
        return data

    lines = [ln.strip() for ln in capture_text.splitlines() if ln.strip()]
    # Heurística simple de conteo
    active = resolved = maint = 0
    today_rows = []
    for ln in lines:
        low = ln.lower()
        if any(k in low for k in ("investigating", "degraded", "outage", "partial", "impact")):
            active += 1
        if "resolved" in low:
            resolved += 1
        if "maintenance" in low or "scheduled" in low:
            maint += 1

        # Fila HTML si parece “línea útil” (descartamos marcas de canal/ts)
        if not (low.startswith("[") and ("] <" in low or "]<" in low)):
            # Evitar duplicar títulos vacíos
            if len(ln) >= 6 and not ln.startswith("**"):
                today_rows.append(
                    f"<tr><td>{vendor}</td><td>-</td><td>{escape_html(ln)}</td>"
                    f"<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
                )

    data["counts"]["active"] = active
    data["counts"]["resolved_today"] = resolved
    data["counts"]["maintenance_today"] = maint
    data["tables"]["today_rows_html"] = "\n".join(today_rows[:200])  # cap por si acaso
    return data

def export_with_fallback(mod, driver, vendor_name: str) -> Dict[str, Any]:
    """
    Preferencias:
      0) (nuevo) Si hay captura de notify -> construir digest desde ahí.
      1) export_for_digest(driver) -> esquema estándar
      2) collect(driver) (legacy) -> normalizar (si algún día vuelve)
      3) Esqueleto con sources.
    """
    # 0) Desde captura
    cap = _read_capture(vendor_name)
    if cap:
        out = _build_from_capture(vendor_name, cap)
        if not out.get("sources"):
            out["sources"] = extract_sources_from_module(mod)
        return out

    # 1) export_for_digest
    exp = getattr(mod, "export_for_digest", None)
    if callable(exp):
        try:
            raw = exp(driver)
            if isinstance(raw, dict) and "tables" in raw and "counts" in raw:
                if "vendor" not in raw:
                    raw["vendor"] = vendor_name
                if "timestamp_utc" not in raw:
                    raw["timestamp_utc"] = now_utc_iso()
                if not raw.get("sources"):
                    raw["sources"] = extract_sources_from_module(mod)
                return raw
        except Exception:
            pass

    # 2) collect(driver) legacy (no lo tienes, pero mantenemos por compat)
    collector = getattr(mod, "collect", None)
    if callable(collector):
        try:
            raw = collector(driver)
            if isinstance(raw, dict):
                # Normalización básica
                out = mk_skeleton(vendor_name)
                incs = (raw.get("incidents_lines") or [])
                active = resolved = maint = 0
                rows = []
                for ln in incs:
                    l = (ln or "").lower()
                    if any(k in l for k in ("investigating","degraded","outage","partial","impact")):
                        active += 1
                    if "resolved" in l:
                        resolved += 1
                    if "maint" in l or "maintenance" in l:
                        maint += 1
                    if ln and "no incidents" not in l:
                        rows.append(
                            f"<tr><td>{vendor_name}</td><td>-</td><td>{escape_html(ln)}</td>"
                            f"<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
                        )
                out["counts"]["active"] = active
                out["counts"]["resolved_today"] = resolved
                out["counts"]["maintenance_today"] = maint
                out["tables"]["today_rows_html"] = "\n".join(rows[:200])
                out["sources"] = raw.get("sources", []) or extract_sources_from_module(mod)
                return out
        except Exception:
            pass

    # 3) Esqueleto
    out = mk_skeleton(vendor_name)
    out["sources"] = extract_sources_from_module(mod)
    return out
