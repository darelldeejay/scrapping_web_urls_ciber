# common/digest_export.py
# -*- coding: utf-8 -*-
import os, json, re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
            "maintenance_today": 0
        },
        "tables": {
            "today_rows_html": "",
            "past15_rows_html": ""
        },
        "sources": [],
        "text": {"vendor_block": ""},
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
        if s and s not in seen:
            out.append(s); seen.add(s)
    return out

def escape_html(s: str) -> str:
    return (s or "").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# --------------------------------------------------------------------
# Capturas y normalización / deduplicación
# --------------------------------------------------------------------

HEADER_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}T.*?Z\]\s*<([a-zA-Z0-9_]+)>\s*$")
NO_INCIDENTS_RE = re.compile(
    r"(no\s+(?:current\s+)?(?:identified\s+)?incidents(?:\s+reported\s+(?:today)?)?"
    r"|incidents\s+today\s*[—\-:]\s*0"
    r"|all\s+systems\s+operational)"
    , re.IGNORECASE
)
ACTIVE_TOKENS_RE = re.compile(
    r"\b(investigating|identified|degraded|partial\s+outage|service\s+disruption|outage|major\s+incident)\b",
    re.IGNORECASE
)
RESOLVED_RE = re.compile(r"\bresolved\b", re.IGNORECASE)
MAINT_RE = re.compile(r"\bmaint(en(ance|imiento))?|scheduled\s+maintenance\b", re.IGNORECASE)

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
    Extrae bloques de un canal (telegram/teams) a partir de cabeceras:
    [timestamp] <canal>
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
            chan = (m.group(1) or "").strip().lower()
            if in_chan == prefer and current:
                blocks.append(current)
            current = []
            in_chan = chan
            continue
        if in_chan == prefer:
            current.append(ln)

    if in_chan == prefer and current:
        blocks.append(current)

    out: List[str] = []
    for b in blocks:
        start = 0; end = len(b)
        while start < end and not b[start].strip(): start += 1
        while end > start and not b[end-1].strip(): end -= 1
        if start < end: out.append("\n".join(b[start:end]))
    return out

# ---------------- Deduplicación genérica ----------------

def _norm_for_dedupe(s: str) -> str:
    """
    Normaliza texto para deduplicación:
    - strip de líneas
    - colapsa múltiple espacio a uno
    - ignora diferencias menores de mayúsculas/espacios
    """
    if not s: return ""
    # normaliza cada línea
    lines = []
    for ln in s.splitlines():
        ln = ln.replace("\xa0", " ")  # nbsp
        ln = re.sub(r"\s+", " ", ln.strip())
        lines.append(ln)
    txt = "\n".join(lines).strip()
    return txt.lower()

def _dedupe_list_of_blocks(blocks: List[str]) -> List[str]:
    """
    Deduplica bloques completos por contenido normalizado, conservando orden.
    """
    out: List[str] = []
    seen: set = set()
    for b in blocks or []:
        nb = _norm_for_dedupe(b)
        if nb in seen:  # duplicado
            continue
        seen.add(nb)
        out.append(b.strip())
    return out

def _split_sections(txt: str) -> List[str]:
    """
    Divide un bloque en secciones por párrafos (2+ saltos de línea).
    """
    parts = re.split(r"(?:\r?\n){2,}", (txt or "").strip())
    # limpia extremos
    return [p.strip() for p in parts if p and p.strip()]

def _dedupe_inside_block(txt: str) -> str:
    """
    Deduplica secciones repetidas dentro del mismo bloque.
    """
    secs = _split_sections(txt)
    out: List[str] = []
    seen: set = set()
    for s in secs:
        ns = _norm_for_dedupe(s)
        if ns in seen:
            continue
        seen.add(ns)
        out.append(s)
    return "\n\n".join(out).strip()

def _prefer_vendor_block(capture_text: str) -> str:
    """
    1) Prefiere Telegram; si no, Teams; si no, texto completo.
    2) Deduplica bloques iguales entre sí.
    3) Deduplica secciones repetidas dentro del bloque resultante.
    """
    tg = _extract_channel_blocks(capture_text, "telegram")
    if tg:
        tg = _dedupe_list_of_blocks(tg)
        return _dedupe_inside_block("\n\n".join(tg))

    tm = _extract_channel_blocks(capture_text, "teams")
    if tm:
        tm = _dedupe_list_of_blocks(tm)
        return _dedupe_inside_block("\n\n".join(tm))

    return _dedupe_inside_block((capture_text or "").strip())

# --------------------------------------------------------------------
# Construcción desde captura (con deduplicación previa)
# --------------------------------------------------------------------

def _build_from_capture(vendor: str, capture_text: str) -> Dict[str, Any]:
    data = mk_skeleton(vendor)
    vendor_block = _prefer_vendor_block(capture_text)

    # (opcional extra) compacta patrones típicos repetidos exactos
    vendor_block = re.sub(
        r"(Component status\s*\n-?\s*All components Operational\s*\n+\s*Incidents today\s*\n-?\s*No incidents reported today)\s*(?:\n+\1)+",
        r"\1",
        vendor_block,
        flags=re.IGNORECASE
    )

    # Cálculos sobre líneas ya deduplicadas
    lines = [ln.strip() for ln in vendor_block.splitlines() if ln.strip()]
    active = resolved = maint = 0
    today_rows: List[str] = []

    # Para evitar filas duplicadas, usamos un conjunto por línea normalizada
    row_seen: set = set()

    for ln in lines:
        low = ln.lower()
        if ACTIVE_TOKENS_RE.search(low): active += 1
        if RESOLVED_RE.search(low): resolved += 1
        if MAINT_RE.search(low): maint += 1

        # Fila HTML “mínima” (evita “no incidents” y duplicados exactos)
        if NO_INCIDENTS_RE.search(low):
            continue
        norm_line = _norm_for_dedupe(ln)
        if norm_line in row_seen:
            continue
        row_seen.add(norm_line)
        if len(ln) >= 3:
            today_rows.append(
                f"<tr><td>{vendor}</td><td>-</td><td>{escape_html(ln)}</td>"
                f"<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
            )

    # Si el bloque afirma “no incidents” y no hay tokens de actividad, forzamos activos=0/resueltos=0
    if NO_INCIDENTS_RE.search(vendor_block) and not ACTIVE_TOKENS_RE.search(vendor_block):
        active = 0
        resolved = 0

    data["counts"]["active"] = active
    data["counts"]["resolved_today"] = resolved
    data["counts"]["maintenance_today"] = maint
    data["tables"]["today_rows_html"] = "\n".join(today_rows[:200])
    data["text"]["vendor_block"] = vendor_block

    return data

# --------------------------------------------------------------------
# Export principal (orden de preferencia con fallback)
# --------------------------------------------------------------------

def export_with_fallback(mod, driver, vendor_name: str) -> Dict[str, Any]:
    """
    Preferencias:
      0) Captura de notificaciones -> datos + bloque de texto (deduplicado).
      1) export_for_digest(driver) -> si lo implementa el vendor.
      2) collect(driver) legacy -> compatibilidad.
      3) Esqueleto mínimo con sources.
    """
    # 0) Desde captura (con dedupe)
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
                # EXTRA: por si este método repite, aplicamos dedupe al vendor_block
                vb = (raw.get("text", {}) or {}).get("vendor_block", "")
                if vb:
                    raw["text"]["vendor_block"] = _dedupe_inside_block(vb)
                # y evitamos filas duplicadas “hoy”
                tbl = (raw.get("tables", {}) or {}).get("today_rows_html", "")
                if tbl:
                    raw["tables"]["today_rows_html"] = _dedupe_table_rows(tbl, vendor_name)
                return raw
        except Exception:
            pass

    # 2) collect(driver) legacy
    collector = getattr(mod, "collect", None)
    if callable(collector):
        try:
            raw = collector(driver)
            if isinstance(raw, dict):
                out = mk_skeleton(vendor_name)
                incs = (raw.get("incidents_lines") or [])

                # Dedup de lineas dentro de collect (por si vinieran duplicadas)
                dedup_incs: List[str] = []
                seen = set()
                for ln in incs:
                    n = _norm_for_dedupe(ln)
                    if n in seen: continue
                    seen.add(n)
                    dedup_incs.append(ln)

                active = resolved = maint = 0
                rows = []
                row_seen = set()
                for ln in dedup_incs:
                    l = (ln or "").lower()
                    if ACTIVE_TOKENS_RE.search(l): active += 1
                    if RESOLVED_RE.search(l): resolved += 1
                    if MAINT_RE.search(l): maint += 1
                    if ln and not NO_INCIDENTS_RE.search(l):
                        n = _norm_for_dedupe(ln)
                        if n in row_seen: continue
                        row_seen.add(n)
                        rows.append(
                            f"<tr><td>{vendor_name}</td><td>-</td><td>{escape_html(ln)}</td>"
                            f"<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
                        )
                block_txt = "\n".join(dedup_incs).strip()
                if NO_INCIDENTS_RE.search(block_txt) and not ACTIVE_TOKENS_RE.search(block_txt):
                    active = 0; resolved = 0
                out["counts"]["active"] = active
                out["counts"]["resolved_today"] = resolved
                out["counts"]["maintenance_today"] = maint
                out["tables"]["today_rows_html"] = "\n".join(rows[:200])
                out["sources"] = raw.get("sources", []) or extract_sources_from_module(mod)
                out["text"]["vendor_block"] = block_txt
                return out
        except Exception:
            pass

    # 3) Esqueleto mínimo
    out = mk_skeleton(vendor_name)
    out["sources"] = extract_sources_from_module(mod)
    return out

# --------------------------------------------------------------------
# Utilidad: dedupe de filas HTML (por si un export_for_digest aporta filas)
# --------------------------------------------------------------------

def _dedupe_table_rows(html_rows: str, vendor: str) -> str:
    """
    Elimina filas HTML duplicadas (misma tercera celda tras normalizar).
    """
    if not html_rows:
        return ""
    # Partimos por cierre de TR y reconstruimos
    parts = re.split(r"(?i)</tr\s*>", html_rows)
    out_parts: List[str] = []
    seen: set = set()
    for p in parts:
        if not p or not p.strip():
            continue
        # intentamos extraer la tercera celda (contenido principal)
        # simplista: quitar tags y colapsar espacios
        cell_txt = re.sub(r"(?is)<[^>]+>", " ", p)
        cell_txt = re.sub(r"\s+", " ", cell_txt).strip().lower()
        if cell_txt in seen:
            continue
        seen.add(cell_txt)
        out_parts.append(p.strip() + "</tr>")
    return "\n".join(out_parts)
