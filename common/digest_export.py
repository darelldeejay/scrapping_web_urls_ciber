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
        if s not in seen:
            out.append(s); seen.add(s)
    return out

def escape_html(s: str) -> str:
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# ---------- Capturas ----------
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

def _prefer_vendor_block(capture_text: str) -> str:
    tg = _extract_channel_blocks(capture_text, "telegram")
    if tg: return "\n\n".join(tg)
    tm = _extract_channel_blocks(capture_text, "teams")
    if tm: return "\n\n".join(tm)
    return (capture_text or "").strip()

def _build_from_capture(vendor: str, capture_text: str) -> Dict[str, Any]:
    data = mk_skeleton(vendor)
    vendor_block = _prefer_vendor_block(capture_text)

    # Conteo SOLO sobre el bloque preferido (evita ruido)
    lines = [ln.strip() for ln in vendor_block.splitlines() if ln.strip()]
    active = resolved = maint = 0
    today_rows = []

    for ln in lines:
        low = ln.lower()
        if ACTIVE_TOKENS_RE.search(low): active += 1
        if RESOLVED_RE.search(low): resolved += 1
        if MAINT_RE.search(low): maint += 1

        # Fila HTML mínima (evita “no incidents”)
        if NO_INCIDENTS_RE.search(low): 
            continue
        if len(ln) >= 3:
            today_rows.append(
                f"<tr><td>{vendor}</td><td>-</td><td>{escape_html(ln)}</td>"
                f"<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
            )

    # Si el bloque afirma “no incidents” y no hay tokens de actividad, forzamos activos=0
    if NO_INCIDENTS_RE.search(vendor_block) and not ACTIVE_TOKENS_RE.search(vendor_block):
        active = 0
        resolved = 0  # resolved_today suele ser 0 en este caso

    data["counts"]["active"] = active
    data["counts"]["resolved_today"] = resolved
    data["counts"]["maintenance_today"] = maint
    data["tables"]["today_rows_html"] = "\n".join(today_rows[:200])
    data["text"]["vendor_block"] = vendor_block

    return data

# ---------- Export principal ----------
def export_with_fallback(mod, driver, vendor_name: str) -> Dict[str, Any]:
    cap = _read_capture(vendor_name)
    if cap:
        out = _build_from_capture(vendor_name, cap)
        if not out.get("sources"):
            out["sources"] = extract_sources_from_module(mod)
        return out

    exp = getattr(mod, "export_for_digest", None)
    if callable(exp):
        try:
            raw = exp(driver)
            if isinstance(raw, dict) and "tables" in raw and "counts" in raw:
                if "vendor" not in raw: raw["vendor"] = vendor_name
                if "timestamp_utc" not in raw: raw["timestamp_utc"] = now_utc_iso()
                if not raw.get("sources"): raw["sources"] = extract_sources_from_module(mod)
                if "text" not in raw: raw["text"] = {"vendor_block": ""}
                return raw
        except Exception:
            pass

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
                    if ACTIVE_TOKENS_RE.search(l): active += 1
                    if RESOLVED_RE.search(l): resolved += 1
                    if MAINT_RE.search(l): maint += 1
                    if ln and not NO_INCIDENTS_RE.search(l):
                        rows.append(
                            f"<tr><td>{vendor_name}</td><td>-</td><td>{escape_html(ln)}</td>"
                            f"<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>"
                        )
                # Si texto indica “no incidents” y no hay tokens de actividad, forzamos 0
                block_txt = "\n".join(incs)
                if NO_INCIDENTS_RE.search(block_txt) and not ACTIVE_TOKENS_RE.search(block_txt):
                    active = 0; resolved = 0
                out["counts"]["active"] = active
                out["counts"]["resolved_today"] = resolved
                out["counts"]["maintenance_today"] = maint
                out["tables"]["today_rows_html"] = "\n".join(rows[:200])
                out["sources"] = raw.get("sources", []) or extract_sources_from_module(mod)
                out["text"]["vendor_block"] = block_txt.strip()
                return out
        except Exception:
            pass

    out = mk_skeleton(vendor_name)
    out["sources"] = extract_sources_from_module(mod)
    return out
