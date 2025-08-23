# common/digest_export.py
# -*- coding: utf-8 -*-
import os, json, re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
        "text": {"vendor_block": ""},  # ⬅️ NUEVO
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

# ---------- Capturas ----------

HEADER_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}T.*?Z\]\s*<([a-zA-Z0-9_]+)>\s*$")

def _read_capture(vendor: str) -> Optional[str]:
    out_dir = os.getenv("DIGEST_OUT_DIR", ".github/out/vendors")
    path = os.path.join(out_dir, f"{vendor}.capture.txt")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
    return None

def _extract_channel_blocks(capture_text: str, prefer: str) -> List[str]:
    """
    Devuelve bloques de texto para un canal concreto (p.ej. 'telegram' o 'teams').
    La captura tiene secciones con cabecera: [timestamp] <canal>
    """
    if not capture_text:
        return []
    lines = capture_text.splitlines()
    blocks: List[List[str]] = []
    current: List[str] = []
    in_chan: Optional[str] = None

    for ln in lines:
        m = HEADER_RE.match(ln.strip())
        if m:
            # Nueva cabecera: cerramos bloque anterior
            chan = (m.group(1) or "").strip().lower()
            if in_chan == prefer and current:
                blocks.append(current)
            # reseteamos
            current = []
            in_chan = chan
            continue

        # Acumulamos líneas sólo si estamos dentro del canal preferido
        if in_chan == prefer:
            current.append(ln)

    # último bloque
    if in_chan == prefer and current:
        blocks.append(current)

    # Limpieza: recorta espacios/lineas vacías en extremos de cada bloque
    out: List[str] = []
    for b in blocks:
        # strip leading/trailing empties
        start = 0
        end = len(b)
        while start < end and not b[start].strip():
            start += 1
        while end > start and not b[end-1].strip():
            end -= 1
        if start < end:
            out.append("\n".join(b[start:end]))
    return out

def _prefer_vendor_block(capture_text: str) -> str:
    # Intentamos Telegram (más plano)
    tg = _extract_channel_blocks(capture_text, "telegram")
    if tg:
        return "\n\n".join(tg)
    # Fallback: Teams
    tm = _extract_channel_blocks(capture_text, "teams")
    if tm:
        return "\n\n".join(tm)
    # Nada: devolvemos captura completa (raro, pero mejor que vacío)
    return (capture_text or "").strip()

def _build_from_capture(vendor: str, capture_text: str) -> Dict[str, Any]:
    data = mk_skeleton(vendor)
    if not capture_text:
        return data

    # Heurística de conteo (sobre la captura completa)
    lines = [ln.strip() for ln in capture_text.splitlines() if ln.strip()]
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
        # Fila HTML “mínima” para el panel de hoy (si no es cabecera de captura)
        if not HEADER_RE.match(ln):
            if len(ln) >= 3:
                today_rows.append(
                    f"<tr><td>{vendor}</td><td>-</td><td>{escape_html(ln)}</td>"
                    f"<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
                )

    data["counts"]["active"] = active
    data["counts"]["resolved_today"] = resolved
    data["counts"]["maintenance_today"] = maint
    data["tables"]["today_rows_html"] = "\n".join(today_rows[:200])

    # ⬅️ Bloque de texto por vendor (preferimos Telegram)
    data["text"]["vendor_block"] = _prefer_vendor_block(capture_text)

    return data

# ---------- Export principal ----------

def export_with_fallback(mod, driver, vendor_name: str) -> Dict[str, Any]:
    """
    Preferencias:
      0) Captura de notificaciones -> construye datos + bloque de texto por vendor.
      1) export_for_digest(driver) -> esquema estándar (si lo implementas en un vendor).
      2) collect(driver) legacy -> normalizar (por compatibilidad).
      3) Esqueleto mínimo con sources.
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
                if "text" not in raw:
                    raw["text"] = {"vendor_block": ""}
                return raw
        except Exception:
            pass

    # 2) collect(driver) legacy (si reaparece)
    collector = getattr(mod, "collect", None)
    if callable(collector):
        try:
            raw = collector(driver)
            if isinstance(raw, dict):
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
                # Texto por vendor (compacto)
                out["text"]["vendor_block"] = "\n".join(incs).strip()
                return out
        except Exception:
            pass

    # 3) Esqueleto
    out = mk_skeleton(vendor_name)
    out["sources"] = extract_sources_from_module(mod)
    return out
