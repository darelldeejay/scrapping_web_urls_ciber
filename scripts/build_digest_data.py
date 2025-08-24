#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Agregador de datos para el digest DORA.

- Lee JSON por vendor desde --vendors-dir (archivos *.json).
- Construye:
    - DETALLES_POR_VENDOR_TEXTO  (bloques uniformes por fabricante)
    - LISTA_FUENTES_CON_ENLACES  (HTML <li><a ...>Nombre</a></li>)
    - FUENTES_TEXTO               (- Nombre: URL)
    - Métricas: NUM_PROVEEDORES, INC_* aproximadas con heurísticas suaves
    - OBS_CLAVE                   (resumen simple según overall_ok / incidencias)
- Escribe un único JSON en --out para que lo consuma run_digest.py
"""

from __future__ import annotations
import argparse
import json
import os
import re
import html
from datetime import datetime, timezone
from typing import Dict, List, Tuple

# ---------------- Utilidades básicas ----------------

TAG_RE = re.compile(r"(?is)<[^>]+>")

def strip_tags(s: str) -> str:
    """Elimina etiquetas HTML y normaliza espacios."""
    if not s:
        return ""
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

# ---------------- Fuentes por vendor ----------------

SOURCES: Dict[str, List[Tuple[str, str]]] = {
    # slug       [(Nombre mostrado, URL), ...]
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
    """Devuelve (LISTA_FUENTES_CON_ENLACES HTML, FUENTES_TEXTO plano)"""
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

# ---------------- Reconstrucción de bloques por vendor ----------------

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
    return (
        v.get("timestamp_utc")
        or v.get("ts_utc")
        or v.get("export_time_utc")
        or now_utc_str()
    )

def normalize_lines(raw: List[str]) -> List[str]:
    """Limpia y homogeneiza líneas eliminando HTML y espacios extra."""
    out = []
    for x in raw or []:
        s = strip_tags(str(x))
        if not s:
            continue
        out.append(s)
    return dedupe_keep_order(out)

def format_vendor_block(slug: str, v: dict) -> str:
    """
    Bloque uniforme:
    === VENDOR ===
    <Título>
    <timestamp> UTC

    Component status
    - ...
    Incidents today
    - ...
    """
    display_slug = (v.get("name") or slug).upper()
    title = NAME_TITLES.get(slug, f"{(v.get('name') or slug.title())} - Status")
    ts = safe_get_timestamp(v)

    comp = normalize_lines(v.get("component_lines") or [])
    inc  = normalize_lines(v.get("incidents_lines") or [])

    lines: List[str] = [
        f"=== {display_slug} ===",
        title,
        f"{ts} UTC",
        "",
        "Component status",
    ]

    if comp:
        for s in comp:
            lines.append(s if s.startswith("- ") else f"- {s}")
    else:
        lines.append("- (no data)")

    lines += ["", "Incidents today"]

    # si viene exactamente "No incidents reported today." nos quedamos con esa idea
    if not inc:
        lines.append("- No incidents reported today")
    else:
        only_no = len(inc) == 1 and "no incidents" in inc[0].lower()
        if only_no:
            lines.append("- No incidents reported today")
        else:
            for s in inc:
                lines.append(s if s.startswith("- ") else f"- {s}")

    return "\n".join(lines)

# ---------------- Heurísticas de métricas ----------------

DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
TODAY = today_utc_date()

ACTIVE_HINTS = ("investigating", "identified", "monitoring", "degraded", "partial outage", "major outage", "not operational")
RESOLVED_HINT = "resolved"
MAINT_HINTS = ("maintenance", "under maintenance", "[scheduled]")

def count_metrics_per_vendor(v: dict) -> Dict[str, int]:
    """
    Heurísticas muy suaves:
      - activos: línea que contenga palabras de ACTIVE_HINTS y no 'resolved'
      - resueltos hoy: línea con 'Fin: YYYY-MM-DD' == hoy, o 'resolved' y alguna fecha de hoy
      - nuevos hoy: línea con 'Inicio: YYYY-MM-DD' == hoy (y sin 'resolved' en la misma línea)
      - mantenimientos hoy: menciones de mantenimiento (si aparece 'YYYY-MM-DD' de hoy sumamos; sino, contamos como 0)
    """
    inc = [strip_tags(str(x)).lower() for x in (v.get("incidents_lines") or []) if str(x).strip()]
    metrics = {"activos": 0, "resueltos_hoy": 0, "nuevos_hoy": 0, "mants_hoy": 0}

    if not inc:
        return metrics

    for ln in inc:
        if "no incidents" in ln:
            continue

        # activos
        if any(h in ln for h in ACTIVE_HINTS) and RESOLVED_HINT not in ln:
            metrics["activos"] += 1

        # fechas
        # Inicio / Fin
        inicio_today = "inicio:" in ln and TODAY in ln
        fin_today    = "fin:" in ln and TODAY in ln

        # fallback por si el formato no tiene "Inicio/Fin" explícitos
        any_today = TODAY in ln

        # nuevos hoy
        if inicio_today and RESOLVED_HINT not in ln:
            metrics["nuevos_hoy"] += 1

        # resueltos hoy
        if fin_today or (RESOLVED_HINT in ln and any_today):
            metrics["resueltos_hoy"] += 1

        # mantenimiento hoy
        if any(h in ln for h in MAINT_HINTS):
            # si aparece fecha de hoy en la línea, contamos
            metrics["mants_hoy"] += 1 if any_today else 0

    return metrics

# ---------------- OBS_CLAVE ----------------

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

# ---------------- Core del agregador ----------------

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
            # normaliza a dict
            if not isinstance(v, dict):
                continue
            data[slug] = v
        except Exception:
            # ignora archivos corruptos
            continue
    return data

def main():
    ap = argparse.ArgumentParser(description="Construye el JSON de datos para el digest DORA")
    ap.add_argument("--vendors-dir", required=True, help="Directorio con JSON por vendor")
    ap.add_argument("--out", required=True, help="Ruta de salida del JSON agregado")
    args = ap.parse_args()

    vendors_data = load_vendor_jsons(args.vendors_dir)
    slugs = sorted(vendors_data.keys())
    num_vendors = len(slugs)

    # Bloques por vendor (siempre uniformes)
    vendor_blocks: List[str] = []
    for slug in slugs:
        vendor_blocks.append(format_vendor_block(slug, vendors_data.get(slug, {}) or {}))
    DETALLES_POR_VENDOR_TEXTO = "\n\n".join(vendor_blocks)

    # Fuentes
    lista_fuentes_html, fuentes_texto = build_sources_lists(slugs)

    # Métricas (sumatorio simple por heurística)
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

    # Tablas ya no se usan en TXT (las dejamos vacías para no duplicar)
    TABLA_INCIDENTES_HOY  = ""
    TABLA_INCIDENTES_15D  = ""

    # Firma opcional (puedes rellenarla en variables de entorno o dejarla vacía)
    firma = os.getenv("DORA_FIRMA_HTML", "").strip()

    data_out = {
        # Conteos
        "NUM_PROVEEDORES": str(num_vendors),
        "INC_NUEVOS_HOY": str(total_nuevos_hoy),
        "INC_ACTIVOS": str(total_activos),
        "INC_RESUELTOS_HOY": str(total_resueltos_hoy),
        "MANTENIMIENTOS_HOY": str(total_mants_hoy),

        # Texto clave
        "OBS_CLAVE": obs,
        "DETALLES_POR_VENDOR_TEXTO": DETALLES_POR_VENDOR_TEXTO,

        # Fuentes
        "LISTA_FUENTES_CON_ENLACES": lista_fuentes_html,
        "FUENTES_TEXTO": fuentes_texto,

        # Tablas (vacías a propósito)
        "TABLA_INCIDENTES_HOY": TABLA_INCIDENTES_HOY,
        "TABLA_INCIDENTES_15D": TABLA_INCIDENTES_15D,

        # Firma (si se desea)
        "FIRMA_HTML": firma,

        # Campos de texto opcionales (pueden cubrirse luego o quedar vacíos)
        "NOMBRE_CONTACTO": os.getenv("DORA_NOMBRE_CONTACTO", "").strip(),
        "ENLACE_O_REFERENCIA_INTERNA": os.getenv("DORA_ENLACE_CRITERIOS", "").strip(),
        "ENLACE_O_TEXTO_CRITERIOS": os.getenv("DORA_ENLACE_CRITERIOS", "").strip(),
        "IMPACTO_CLIENTE_SI_NO": "",     # se puede sobreescribir desde workflow
        "ACCION_SUGERIDA": "",           # se puede sobreescribir desde workflow
        "FECHA_SIGUIENTE_REPORTE": today_utc_date(),
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)

    print(f"[build_digest_data] OK -> {args.out} ({num_vendors} vendors)")

if __name__ == "__main__":
    main()
