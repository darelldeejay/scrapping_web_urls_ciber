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
- Tolera: strings, listas, listas de dicts, dicts con 'items', HTML con <a>.
- Preserva URLs como 'Texto (URL)' y limpia etiquetas.
- Genera:
    * DETALLES_POR_VENDOR_TEXTO
    * LISTA_FUENTES_CON_ENLACES (HTML)
    * FUENTES_TEXTO (plain)
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
# <a href="...">texto</a>  ->  texto (URL)
A_HREF_RE = re.compile(r'(?is)<a\b[^>]*\bhref=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a\s*>')

def anchor_to_text(s: str) -> str:
    def repl(m: re.Match) -> str:
        url = m.group(1).strip()
        text = m.group(2).strip()
        text_clean = TAG_RE.sub("", text)
        return f"{html.unescape(text_clean)} ({url})"
    return A_HREF_RE.sub(repl, s)

def strip_tags(s: str) -> str:
    """Elimina etiquetas HTML y normaliza espacios."""
    if not s:
        return ""
    # Antes de quitar etiquetas, convierte <a> a "texto (URL)"
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
    """
    Acepta:
      - "2025-08-24 00:10"
      - "2025-08-24T00:10:19Z"
      - "2025-08-24T00:10:19+00:00"
    Devuelve "YYYY-MM-DD HH:MM"
    """
    if not ts:
        return now_utc_str()
    s = str(ts).strip()
    # Si ya viene con espacio y HH:MM, deja tal cual (mini-normalización)
    try:
        if "T" in s:
            # ISO
            try:
                # 2025-08-24T00:10:19Z  /  2025-08-24T00:10:19+00:00
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                dt = dt.astimezone(timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        # Intento directo
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                continue
    except Exception:
        pass
    # Fallback: devuelve s sin 'T' y 'Z' bonificado
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

def coerce_to_lines(raw: Any) -> List[str]:
    """
    Convierte diferentes formas a lista de líneas:
      - None -> []
      - str  -> splitlines(), strip, elimina vacías
      - list[str] -> limpia/normaliza
      - list[dict] con (name,status) -> "name status"
      - dict con 'items' -> usa items (string o lista)
      - dict con 'children' -> "name status" de los hijos
    """
    if raw is None:
        return []
    # dict con 'items'
    if isinstance(raw, dict):
        items = raw.get("items")
        if items is not None:
            return coerce_to_lines(items)
        # children (ej. grupos de componentes)
        children = raw.get("children")
        if isinstance(children, list):
            out = []
            for c in children:
                if isinstance(c, dict):
                    nm = strip_tags(str(c.get("name") or "")).strip()
                    st = strip_tags(str(c.get("status") or "")).strip()
                    if nm and st:
                        out.append(f"{nm} {st}")
                    elif nm:
                        out.append(nm)
            return out
        # dict plano -> intenta concatenar valores relevantes
        name = raw.get("name")
        status = raw.get("status")
        if name or status:
            nm = strip_tags(str(name or "")).strip()
            st = strip_tags(str(status or "")).strip()
            return [f"{nm} {st}".strip()]
        return []

    # string
    if isinstance(raw, str):
        lines = [strip_tags(x) for x in str(raw).splitlines()]
        return [x for x in (l.strip() for l in lines) if x]

    # lista
    if isinstance(raw, list):
        out: List[str] = []
        for el in raw:
            if isinstance(el, str):
                s = strip_tags(el)
                if s:
                    out.append(s)
            elif isinstance(el, dict):
                nm = strip_tags(str(el.get("name") or "")).strip()
                st = strip_tags(str(el.get("status") or "")).strip()
                it = el.get("items")
                ch = el.get("children")
                if nm or st:
                    out.append(f"{nm} {st}".strip())
                if it is not None:
                    out += coerce_to_lines(it)
                if ch is not None:
                    out += coerce_to_lines(ch)
            else:
                s = strip_tags(str(el))
                if s:
                    out.append(s)
        # limpia duplicados y vacíos
        out = [x for x in (o.strip() for o in out) if x]
        return dedupe_keep_order(out)

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
    return coerce_timestamp(ts)

def format_vendor_block(slug: str, v: dict) -> str:
    """
    Bloque uniforme visible para cliente final.
    """
    display_slug = (v.get("name") or slug).upper()
    title = NAME_TITLES.get(slug, f"{(v.get('name') or slug.title())} - Status")
    ts = safe_get_timestamp(v)

    # Recupera posibles campos heterogéneos
    comp_raw = v.get("component_lines")
    inc_raw  = v.get("incidents_lines")

    # Fallbacks frecuentes
    if not comp_raw:
        # akamai/guardicore suele tener 'groups'
        if "groups" in v:
            comp_raw = v.get("groups")
        elif "components" in v:
            comp_raw = v.get("components")
        elif "status" in v and isinstance(v["status"], dict):
            comp_raw = v["status"].get("components")

    if not inc_raw:
        if "incidents" in v:
            inc_raw = v.get("incidents")
        elif "sections" in v:
            inc_raw = v.get("sections")
        elif "banner" in v:
            inc_raw = v.get("banner")

    comp = coerce_to_lines(comp_raw)
    inc  = coerce_to_lines(inc_raw)

    # Para algunos vendors (CyberArk), el banner de estado es útil en un bloque aparte
    banner = strip_tags(str(v.get("banner") or v.get("overall_status") or "")).strip()

    lines: List[str] = [
        f"=== {display_slug} ===",
        title,
        f"{ts} UTC",
        "",
    ]

    # Si el vendor trae un "System/Overall status" textual, muéstralo como bloque corto
    if banner:
        lines.append(banner)
        lines.append("")  # línea en blanco

    # Componentes
    lines.append("Component status")
    if comp:
        for s in dedupe_keep_order(comp):
            lines.append(s if s.startswith("- ") else f"- {s}")
    else:
        lines.append("- (no data)")

    # Incidentes
    lines += ["", "Incidents today"]
    if not inc:
        lines.append("- No incidents reported today.")
    else:
        only_no = len(inc) == 1 and "no incidents" in inc[0].lower()
        if only_no:
            lines.append("- No incidents reported today.")
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
    inc = coerce_to_lines(v.get("incidents_lines"))
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
    if oks == total:
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
            # ignora archivos corruptos
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

    # Bloques por vendor
    vendor_blocks: List[str] = []
    for slug in slugs:
        vendor_blocks.append(format_vendor_block(slug, vendors_data.get(slug, {}) or {}))
    DETALLES_POR_VENDOR_TEXTO = "\n\n".join(vendor_blocks)

    # Fuentes
    lista_fuentes_html, fuentes_texto = build_sources_lists(slugs)

    # Métricas
    total_activos = total_resueltos_hoy = total_nuevos_hoy = total_mants_hoy = 0
    for slug in slugs:
        v = vendors_data.get(slug, {}) or {}
        m = count_metrics_per_vendor(v)
        total_activos       += m["activos"]
        total_resueltos_hoy += m["resueltos_hoy"]
        total_nuevos_hoy    += m["nuevos_hoy"]
        total_mants_hoy     += m["mants_hoy"]

    # Observación
    obs = build_obs_clave(vendors_data)

    # Tablas (las dejamos vacías si no las usas en TXT)
    TABLA_INCIDENTES_HOY  = ""
    TABLA_INCIDENTES_15D  = ""

    # Firma opcional
    firma = os.getenv("DORA_FIRMA_HTML", "").strip()

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

        "TABLA_INCIDENTES_HOY": TABLA_INCIDENTES_HOY,
        "TABLA_INCIDENTES_15D": TABLA_INCIDENTES_15D,

        "FIRMA_HTML": firma,

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
