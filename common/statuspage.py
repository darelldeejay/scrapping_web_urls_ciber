# common/statuspage.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import requests, re
from datetime import datetime, timezone
from typing import Dict, List, Any

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")

def _now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def _fmt_utc(s: str) -> str:
    """Devuelve 'YYYY-MM-DD HH:MM UTC' desde ISO/otros."""
    try:
        if ISO_RE.search(s):
            dt = datetime.fromisoformat(s.replace("Z","+00:00"))
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return s

def fetch_summary(base_url: str, timeout: int = 20) -> Dict[str, Any]:
    base = base_url.rstrip("/")
    url = f"{base}/api/v2/summary.json"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "dora-bot/1.0"})
    r.raise_for_status()
    return r.json()

def parse_components(summary: Dict[str, Any]) -> List[str]:
    comps = summary.get("components") or []
    # Construye índice por id y asociación grupo->hijos
    by_id = {c.get("id"): c for c in comps}
    groups = [c for c in comps if c.get("group")]
    children_map = {}
    for g in groups:
        ids = g.get("components") or []
        children_map[g["id"]] = [by_id[i] for i in ids if i in by_id]

    lines: List[str] = []
    # Preferimos vista por grupos si existen
    if groups:
        for g in groups:
            childs = children_map.get(g["id"], [])
            if not childs:
                # Grupo sin hijos listados; mostrar su estado si viene
                st = g.get("status") or "unknown"
                if st != "operational":
                    lines.append(f"{g['name']} {st.replace('_',' ').title()}")
                continue
            # Si todos operacionales → 'Grupo Operational'; si no, listar sólo no-operacionales
            non_ok = [c for c in childs if (c.get("status") or "") != "operational"]
            if not non_ok:
                lines.append(f"{g['name']} Operational")
            else:
                lines.append(g["name"])
                for c in non_ok:
                    st = (c.get("status") or "unknown").replace("_"," ").title()
                    lines.append(f"- {c['name']} {st}")
    else:
        # Sin grupos: lista sólo no-operacionales
        for c in comps:
            st = (c.get("status") or "unknown")
            if not c.get("group") and st != "operational":
                lines.append(f"{c['name']} {st.replace('_',' ').title()}")

    # Compacta duplicados manteniendo orden
    seen, out = set(), []
    for ln in lines:
        if ln not in seen:
            seen.add(ln); out.append(ln)
    return out

def parse_incidents_today(summary: Dict[str, Any]) -> List[str]:
    items = summary.get("incidents") or []
    today_lines: List[str] = []
    if not items:
        return ["No incidents reported today"]
    today = datetime.now(timezone.utc).date()
    for inc in items:
        name = inc.get("name") or "Incident"
        status = (inc.get("status") or "").title()
        # última actualización del propio incidente
        updates = inc.get("incident_updates") or []
        last = None
        if updates:
            # coge el último por updated_at / created_at
            last = max(updates, key=lambda u: u.get("updated_at") or u.get("created_at") or "")
        ts = last.get("updated_at") if last else inc.get("updated_at") or inc.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(timezone.utc)
        except Exception:
            continue
        if dt.date() == today:
            when = dt.strftime("%Y-%m-%d %H:%M UTC")
            today_lines.append(f"{name} — {status} (last update {when})")
    return today_lines or ["No incidents reported today"]

def build_statuspage_result(name: str, base_url: str) -> Dict[str, Any]:
    try:
        summary = fetch_summary(base_url)
        comp = parse_components(summary)
        inc = parse_incidents_today(summary)
        overall_ok = (inc == ["No incidents reported today"]) and all("Operational" in x for x in comp) if comp else (inc == ["No incidents reported today"])
        return {
            "name": name,
            "timestamp_utc": _now_utc_str(),
            "component_lines": comp,
            "incidents_lines": inc,
            "overall_ok": overall_ok,
        }
    except Exception as e:
        # Fallback sin datos
        return {
            "name": name,
            "timestamp_utc": _now_utc_str(),
            "component_lines": [],
            "incidents_lines": [f"(statuspage fetch error: {e})", "No incidents reported today"],
            "overall_ok": None,
        }
