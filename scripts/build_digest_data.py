#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Agregador de datos para el digest DORA (robusto frente a formatos heterogéneos).
- Lee JSON por vendor desde --vendors-dir (archivos *.json).
- Reconstruye bloques por fabricante con:
    === VENDOR ===
    <Título>
    <timestamp> UTC

    Component status
    - ...
    Incidents today
    - ...
- Tolera: strings, listas, listas de dicts, dicts con 'items', 'children', 'groups', 'sections', HTML <a>, etc.
- Preserva URLs como 'Texto (URL)' y limpia etiquetas.
- Genera:
    * DETALLES_POR_VENDOR_TEXTO
    * LISTA_FUENTES_CON_ENLACES (HTML)
    * FUENTES_TEXTO (plain con URL)
    * Métricas básicas y OBS_CLAVE
"""

from __future__ import annotations
import argparse
import json
import os
import re
import html
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Any

# ========== Utilidades de formato ==========

TAG_RE = re.compile(r"(?is)<[^>]+>")
A_HREF_RE = re.compile(r'(?is)<a\b[^>]*\bhref=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a\s*>')

def anchor_to_text(s: str) -> str:
    def repl(m: re.Match) -> str:
        url = m.group(1).strip()
        text = m.group(2).strip()
        text_clean = TAG_RE.sub("", text)
        return f"{html.unescape(text_clean)} ({url})"
    return A_HREF_RE.sub(repl, s)

def strip_tags(s: str) -> str:
    if not s:
        return ""
    s = anchor_to_text(s)
    s = TAG_RE.sub("", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", s).strip()

def dedupe_keep_order(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in seq:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out

def now_utc_str(fmt: str = "%Y-%m-%d %H:%M") -> str:
    return datetime.now(timezone.utc).strftime(fmt)

def today_utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def coerce_timestamp(ts: Any) -> str:
    if not ts:
        return now_utc_str()
    s = str(ts).strip()
    try:
        if "T" in s:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                continue
    except Exception:
        pass
    s = s.replace("T", " ").replace("Z", "")
    return s[:16]

# ========== Fuentes por vendor ==========

SOURCES: Dict[str, List[Tuple[str, str]]] = {
    "aruba":      [("Aruba Central — Status", "https://centralstatus.arubanetworking.hpe.com/")],
    "cyberark":   [("CyberArk Privilege Cloud — Status", "https://privilegecloud-service-status.cyberark.com/")],
    "guardicore": [("Akamai (Guardicore) — Status", "https://www.akamaistatus.com/")],
    "imperva":    [("Imperva — Status", "https://status.imperva.com/")],
    "proofpoint": [("Proofpoint — Current Incidents", "https://proofpoint.my.site.com/community/s/proofpoint-current-incidents")],
    "qualys":     [("Qualys — Status History", "https://status.qualys.com/history?filter=8f7fjwhmd4n0")],
    "trendmicro": [
        ("Trend Micro — Trend Cloud One", "https://status.trendmicro.com/en-US/trend-cloud-one/"),
        ("Trend Micro — Trend Vision One", "https://status.trendmicro.com/en-US/trend-vision-one/"),
    ],
    "netskope":   [("Netskope — Trust Portal", "https://trustportal.netskope.com/")],
}

def build_sources_lists(slugs: List[str]) -> Tuple[str, str]:
    items_html: List[str] = []
    items_txt: List[str] = []
    seen = set()
    for slug in slugs:
        for name, url in SOURCES.get(slug, []):
            key = (name, url)
            if key in seen:
                continue
            seen.add(key)
            items_html.append(f'<li><a href="{url}">{html.escape(name)}</a></li>')
            items_txt.append(f"- {name}: {url}")
    return "\n".join(items_html), "\n".join(items_txt)

# ========== Reconstrucción de líneas desde JSON heterogéneo ==========

def split_to_lines(s: str) -> List[str]:
    return [x.strip() for x in s.splitlines() if x.strip()]

def coerce_to_lines(raw: Any) -> List[str]:
    """
    Convierte diferentes formas a lista de líneas utilizables:
      - None -> []
      - str  -> splitlines(), strip, elimina vacías (conversión <a> previa)
      - list[str] -> limpia/normaliza
      - list[dict] con (name,status,items,children) -> "name status" + recursión
      - dict con 'items' o 'children' -> usa esos campos
    """
    if raw is None:
        return []

    if isinstance(raw, dict):
        # items / children
        if "items" in raw:
            return coerce_to_lines(raw.get("items"))
        if "children" in raw:
            return coerce_to_lines(raw.get("children"))

        nm = raw.get("name")
        st = raw.get("status")
        if nm or st:
            nm = strip_tags(str(nm or ""))
            st = strip_tags(str(st or ""))
            return [f"{nm} {st}".strip()]
        return []

    if isinstance(raw, str):
        s = strip_tags(raw)
        return split_to_lines(s)

    if isinstance(raw, list):
        out: List[str] = []
        for el in raw:
            if isinstance(el, str):
                out += split_to_lines(strip_tags(el))
            elif isinstance(el, dict):
                nm = strip_tags(str(el.get("name") or ""))
                st = strip_tags(str(el.get("status") or ""))
                if nm or st:
                    out.append(f"{nm} {st}".strip())
                if "items" in el:
                    out += coerce_to_lines(el["items"])
                if "children" in el:
                    out += coerce_to_lines(el["children"])
                if "text" in el and isinstance(el["text"], str):
                    out += split_to_lines(strip_tags(el["text"]))
            else:
                out += split_to_lines(strip_tags(str(el)))
        return dedupe_keep_order([x for x in out if x])
    # fallback
    s = strip_tags(str(raw))
    return [s] if s else []

# ========== Reconstrucción de bloques por vendor ==========

NAME_TITLES = {
    "aruba":      "Aruba Central - Status",
    "cyberark":   "CyberArk Privilege Cloud - Status",
    "guardicore": "Akamai (Guardicore) - Status",
    "imperva":    "Imperva - Status",
    "netskope":   "Netskope - Estado de Incidentes",
    "proofpoint": "Proofpoint - Estado de Incidentes",
    "qualys":     "Qualys - Estado de Incidentes",
    "trendmicro": "Trend Micro - Status",
}

def safe_get_timestamp(v: dict) -> str:
    ts = v.get("timestamp_utc") or v.get("ts_utc") or v.get("export_time_utc") or ""
    return coerce_timestamp(ts) if ts else now_utc_str()

def best_comp_lines(slug: str, v: dict) -> List[str]:
    # candidatos típicos
    for key in ("component_lines", "components", "groups", "component_status", "status_lines"):
        if key in v and v[key]:
            return coerce_to_lines(v[key])

    # banner/overall como pista
    banner = v.get("banner") or v.get("overall_status")
    if banner:
        b = strip_tags(str(banner))
        return [b] if b else []

    # overall_ok -> relleno decente
    if v.get("overall_ok") is True:
        # estilos por vendor
        if slug in ("aruba", "guardicore", "imperva"):
            return ["All components Operational"]
        if slug == "netskope":
            return ["Estado general: Operational"]
        if slug == "cyberark":
            return ["System status: All Systems Operational"]
        return ["All Systems Operational"]

    return []

def best_inc_lines(slug: str, v: dict) -> List[str]:
    # candidatos habituales
    for key in ("incidents_lines", "incidents", "sections", "banner", "today", "today_incidents", "incidents_today", "console_lines", "console_text"):
        if key in v and v[key]:
            lines = coerce_to_lines(v[key])
            if lines:
                return lines
    return []

def format_vendor_block(slug: str, v: dict) -> str:
    display_slug = (v.get("name") or slug).upper()
    title = NAME_TITLES.get(slug, f"{(v.get('name') or slug.title())} - Status")
    ts = safe_get_timestamp(v)

    comp = best_comp_lines(slug, v)
    inc  = best_inc_lines(slug, v)

    # Netskope: si hay estructura clásica, mantenemos headings
    netskope_headings = {
        "Incidentes activos": ("incidentes activos", "active incidents"),
        "Últimos 15 días (resueltos)": ("últimos 15 días", "last 15 days", "past incidents"),
    }

    lines: List[str] = [f"=== {display_slug} ===", title, f"{ts} UTC", ""]

    # CyberArk / Imperva a veces traen banner útil
    banner = strip_tags(str(v.get("banner") or v.get("overall_status") or "")).strip()
    if banner:
        lines.append(banner)
        lines.append("")

    # Componentes
    lines.append("Component status")
    if comp:
        for s in dedupe_keep_order(comp):
            lines.append(s if s.startswith("- ") else f"- {s}")
    else:
        # si no hay nada pero sabemos que todo ok
        if v.get("overall_ok") is True:
            if slug == "cyberark":
                lines.append("- All Systems Operational")
            else:
                lines.append("- All components Operational")
        else:
            lines.append("- (no data)")

    # Incidentes
    lines += ["", "Incidents today"]
    if not inc:
        lines.append("- No incidents reported today.")
    else:
        # si sólo viene una línea 'No incidents ...'
        only_no = len(inc) == 1 and "no incidents" in inc[0].lower()
        if only_no:
            lines.append("- No incidents reported today.")
        else:
            # para Netskope, intenta preservar headings típicos
            if slug == "netskope":
                # Recompone en dos bloques si detecta keywords
                lower_join = "\n".join(inc).lower()
                if any(k in lower_join for k in netskope_headings["Incidentes activos"]):
                    lines.append("Incidentes activos")
                # vuelca líneas
                for s in dedupe_keep_order(inc):
                    lines.append(s if s.startswith("- ") else f"- {s}")
            else:
                for s in dedupe_keep_order(inc):
                    lines.append(s if s.startswith("- ") else f"- {s}")

    return "\n".join(lines)

# ========== Métricas básicas (heurísticas) ==========

TODAY = today_utc_date()
ACTIVE_HINTS = ("investigating", "identified", "monitoring", "degraded", "partial outage", "major outage", "not operational")
RESOLVED_HINT = "resolved"
MAINT_HINTS = ("maintenance", "under maintenance", "[scheduled]")

def count_metrics_per_vendor(v: dict) -> Dict[str, int]:
    inc = best_inc_lines("", v)
    inc_lc = [x.lower() for x in inc]
    m = {"activos": 0, "resueltos_hoy": 0, "nuevos_hoy": 0, "mants_hoy": 0}
    for ln in inc_lc:
        if "no incidents" in ln:
            continue
        if any(h in ln for h in ACTIVE_HINTS) and RESOLVED_HINT not in ln:
            m["activos"] += 1
        inicio_today = ("inicio:" in ln and TODAY in ln)
        fin_today    = ("fin:" in ln and TODAY in ln)
        any_today    = TODAY in ln
        if inicio_today and RESOLVED_HINT not in ln:
            m["nuevos_hoy"] += 1
        if fin_today or (RESOLVED_HINT in ln and any_today):
            m["resueltos_hoy"] += 1
        if any(h in ln for h in MAINT_HINTS) and any_today:
            m["mants_hoy"] += 1
    return m

# ========== OBS_CLAVE ==========

def build_obs_clave(vendors: Dict[str, dict]) -> str:
    if not vendors:
        return "No hay datos de fabricantes para este periodo."
    total = len(vendors)
    oks = sum(1 for v in vendors.values() if v.get("overall_ok") is True)
    if oks == total and total > 0:
        return "Todos los fabricantes reportan estado operacional sin incidentes hoy."
    afect = total - oks
    if afect <= 0:
        return "Sin señales de incidencia relevantes hoy."
    return f"Se observa actividad en {afect} de {total} fabricantes (ver detalle por fabricante)."

# ========== Lectura de JSONs y generación del agregado ==========

def load_vendor_jsons(vendors_dir: str) -> Dict[str, dict]:
    data: Dict[str, dict] = {}
    if not os.path.isdir(vendors_dir):
        return data
    for fname in sorted(os.listdir(vendors_dir)):
        if not fname.endswith(".json"):
            continue
        slug = os.path.splitext(fname)[0].lower()
        path = os.path.join(vendors_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                v = json.load(f)
            if isinstance(v, dict):
                data[slug] = v
        except Exception:
            continue
    return data

def main():
    ap = argparse.ArgumentParser(description="Construye el JSON de datos para el digest DORA (robusto)")
    ap.add_argument("--vendors-dir", required=True, help="Directorio con JSON por vendor")
    ap.add_argument("--out", required=True, help="Ruta de salida del JSON agregado")
    args = ap.parse_args()

    vendors_data = load_vendor_jsons(args.vendors_dir)
    slugs = sorted(vendors_data.keys())
    num_vendors = len(slugs)

    vendor_blocks: List[str] = []
    for slug in slugs:
        vendor_blocks.append(format_vendor_block(slug, vendors_data.get(slug, {}) or {}))
    DETALLES_POR_VENDOR_TEXTO = "\n\n".join(vendor_blocks)

    lista_fuentes_html, fuentes_texto = build_sources_lists(slugs)

    total_activos = total_resueltos_hoy = total_nuevos_hoy = total_mants_hoy = 0
    for slug in slugs:
        v = vendors_data.get(slug, {}) or {}
        m = count_metrics_per_vendor(v)
        total_activos       += m["activos"]
        total_resueltos_hoy += m["resueltos_hoy"]
        total_nuevos_hoy    += m["nuevos_hoy"]
        total_mants_hoy     += m["mants_hoy"]

    obs = build_obs_clave(vendors_data)

    data_out = {
        "NUM_PROVEEDORES": str(num_vendors),
        "INC_NUEVOS_HOY": str(total_nuevos_hoy),
        "INC_ACTIVOS": str(total_activos),
        "INC_RESUELTOS_HOY": str(total_resueltos_hoy),
        "MANTENIMIENTOS_HOY": str(total_mants_hoy),

        "OBS_CLAVE": obs,
        "DETALLES_POR_VENDOR_TEXTO": DETALLES_POR_VENDOR_TEXTO,

        "LISTA_FUENTES_CON_ENLACES": lista_fuentes_html,
        "FUENTES_TEXTO": fuentes_texto,

        "TABLA_INCIDENTES_HOY": "",
        "TABLA_INCIDENTES_15D": "",

        "FIRMA_HTML": os.getenv("DORA_FIRMA_HTML", "").strip(),
        "NOMBRE_CONTACTO": os.getenv("DORA_NOMBRE_CONTACTO", "").strip(),
        "ENLACE_O_REFERENCIA_INTERNA": os.getenv("DORA_ENLACE_CRITERIOS", "").strip(),
        "ENLACE_O_TEXTO_CRITERIOS": os.getenv("DORA_ENLACE_CRITERIOS", "").strip(),
        "IMPACTO_CLIENTE_SI_NO": "",
        "ACCION_SUGERIDA": "",
        "FECHA_SIGUIENTE_REPORTE": today_utc_date(),
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)

    print(f"[build_digest_data] OK -> {args.out} ({num_vendors} vendors)")

if __name__ == "__main__":
    main()
