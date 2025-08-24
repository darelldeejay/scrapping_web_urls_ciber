#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Construye el JSON de datos para las plantillas DORA (txt y html).

- Lee todos los *.json de --vendors-dir (salida de run_vendor.py --export-json).
- Normaliza y compone:
  * DETALLES_POR_VENDOR_TEXTO (bloques por fabricante en texto plano)
  * Contadores (aprox.) de incidencias del día y mantenimientos
  * Fuentes en dos variantes:
      - LISTA_FUENTES_CON_ENLACES (HTML <li><a ...>)
      - LISTA_FUENTES_TXT (viñetas planas para texto)
- Escribe el JSON listo para que run_digest.py haga el render.

NOTA: Este script NO envía nada; solo prepara datos.
"""

import os
import re
import json
import glob
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple

# ---------------------------------------------------------------------------
# Fuentes (mantener sincronizadas con vendors soportados)
# ---------------------------------------------------------------------------

SOURCES = [
    ("Aruba Central — Status", "https://centralstatus.arubanetworking.hpe.com/"),
    ("CyberArk Privilege Cloud — Status", "https://privilegecloud-service-status.cyberark.com/"),
    ("Akamai (Guardicore) — Status", "https://www.akamaistatus.com/"),
    ("Imperva — Status", "https://status.imperva.com/"),
    ("Netskope — Trust Portal", "https://trustportal.netskope.com/incidents"),
    ("Proofpoint — Current Incidents", "https://proofpoint.my.site.com/community/s/proofpoint-current-incidents"),
    ("Qualys — Status History", "https://status.qualys.com/history?filter=8f7fjwhmd4n0"),
    ("Trend Micro — Trend Cloud One", "https://status.trendmicro.com/en-US/trend-cloud-one/"),
    ("Trend Micro — Trend Vision One", "https://status.trendmicro.com/en-US/trend-vision-one/"),
]

def build_sources_blocks() -> Tuple[str, str]:
    """Devuelve (html_ul_items, txt_bullets)"""
    html = "".join(f'<li><a href="{url}">{label}</a></li>\n' for label, url in SOURCES)
    txt  = "\n".join(f"- {label}" for label, _ in SOURCES)
    return html, txt

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

STATUS_RESOLVED_RE = re.compile(r"\bResolved\b", re.I)
STATUS_ANY_TODAY_RE = re.compile(
    r"\b(Investigating|Identified|Update|Mitigated|Monitoring|Degraded|Incident)\b", re.I
)
UNDER_MAINT_RE = re.compile(r"\bUnder Maintenance\b", re.I)

def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _safe_lines(x) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        # aplanar por si vienen párrafos con \n
        out: List[str] = []
        for it in x:
            if isinstance(it, str):
                out.extend(it.splitlines())
        return [ln.rstrip() for ln in out]
    if isinstance(x, str):
        return x.splitlines()
    return []

def _fmt_timestamp(ts: str) -> str:
    """Adapta 'YYYY-MM-DD HH:MM' o ISO a 'YYYY-MM-DD HH:MM' (UTC explícito lo añade el render)."""
    if not ts:
        return ""
    s = ts.strip()
    # ISO → 'YYYY-MM-DD HH:MM'
    s = s.replace("T", " ")
    s = s.replace("Z", "")
    # recorta a minutos
    m = re.match(r"^\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", s)
    if m:
        return m.group(1)
    # último recurso: si ya viene "YYYY-MM-DD HH:MM UTC", déjalo tal cual
    return s

def _title_for_vendor(name: str) -> str:
    """Título visible debajo del '=== VENDOR ==='."""
    n = (name or "").strip()
    if n.lower().startswith("netskope"):
        return "Netskope - Estado de Incidentes"
    if n.lower().startswith("proofpoint"):
        return "Proofpoint - Estado de Incidentes"
    if n.lower().startswith("qualys"):
        return "Qualys - Estado de Incidentes"
    if n.lower().startswith("imperva"):
        return "Imperva - Status"
    if n.lower().startswith("akamai") or "guardicore" in n.lower():
        return "Akamai (Guardicore) - Status"
    if n.lower().startswith("cyberark"):
        return "CyberArk Privilege Cloud - Status"
    if n.lower().startswith("aruba"):
        return "Aruba Central - Status"
    if n.lower().startswith("trend"):
        return "Trend Micro - Status"
    return f"{n} - Status"

# ---------------------------------------------------------------------------
# Construcción de “Detalles por fabricante” (texto plano)
# ---------------------------------------------------------------------------

def build_vendor_block(v: Dict[str, Any]) -> str:
    """
    Recibe el JSON exportado por el vendor:
      { name, timestamp_utc, component_lines: [..], incidents_lines: [..], overall_ok: bool }
    Devuelve un bloque de texto homogéneo sin HTML.
    """
    name = v.get("name") or "Vendor"
    ts   = _fmt_timestamp(v.get("timestamp_utc", ""))

    comp_lines = _safe_lines(v.get("component_lines"))
    inc_lines  = _safe_lines(v.get("incidents_lines"))
    overall_ok = bool(v.get("overall_ok"))

    # Cabecera
    out: List[str] = []
    out.append(f"=== {name.upper()} ===")
    out.append(_title_for_vendor(name))
    if ts:
        out.append(f"{ts} UTC")
    out.append("")

    # Component status
    # Si el vendor ya formatea su propio encabezado (p.ej. "Component status"), no reinsertar.
    has_comp_header = any(re.search(r"^\s*Component status\s*$", ln, re.I) for ln in comp_lines)
    if not has_comp_header:
        out.append("Component status")
    if comp_lines:
        # Normalizar viñetas
        for ln in comp_lines:
            ln = ln.strip()
            if not ln:
                continue
            if ln.startswith(("-", "•")):
                out.append(ln)
            else:
                out.append(f"- {ln}")
    else:
        # Sin componentes: si overall_ok decimos "All components Operational", si no, "(no data)"
        out.append("- All components Operational" if overall_ok else "- (no data)")

    # Incidents today
    out.append("")
    # Evitar duplicar el encabezado si ya viene incluido
    has_inc_header = any(re.search(r"^\s*Incidents today\s*$", ln, re.I) for ln in inc_lines)
    if not has_inc_header:
        out.append("Incidents today")
    if inc_lines:
        # Si las líneas incluyen párrafos con encabezados propios (Trend Micro), respétalos.
        empty_acc = True
        for ln in inc_lines:
            ln = ln.rstrip()
            if ln.strip():
                empty_acc = False
            out.append(ln)
        if empty_acc:
            out.append("- No incidents reported today.")
    else:
        out.append("- No incidents reported today.")

    return "\n".join(out).rstrip()

# ---------------------------------------------------------------------------
# Cómputo simple de contadores (aprox.)
# ---------------------------------------------------------------------------

def compute_counters(vendors: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Heurística:
      - RESUELTOS_HOY: líneas que contienen 'Resolved'.
      - NUEVOS_HOY: líneas que contienen estados típicos (Investigating, Identified, Update,
                    Mitigated, Monitoring, Degraded, Incident) y NO 'Resolved'.
      - ACTIVOS: difícil de inferir sin estructura; lo dejamos en 0 (evita confundir).
      - MANTENIMIENTOS_HOY: líneas de componentes con 'Under Maintenance'.
    """
    nuevos = 0
    resueltos = 0
    activos = 0
    mant = 0

    for v in vendors:
        # incidents
        for ln in _safe_lines(v.get("incidents_lines")):
            if STATUS_RESOLVED_RE.search(ln):
                resueltos += 1
            elif STATUS_ANY_TODAY_RE.search(ln):
                nuevos += 1
        # components
        for ln in _safe_lines(v.get("component_lines")):
            if UNDER_MAINT_RE.search(ln):
                mant += 1

    return {
        "INC_NUEVOS_HOY": nuevos,
        "INC_ACTIVOS": activos,
        "INC_RESUELTOS_HOY": resueltos,
        "MANTENIMIENTOS_HOY": mant,
    }

# ---------------------------------------------------------------------------
# OBS_CLAVE y campos auxiliares
# ---------------------------------------------------------------------------

def build_obs_clave(vendors: List[Dict[str, Any]]) -> str:
    """
    Observación breve:
     - Si todo OK → "Sin novedades relevantes."
     - Si hay alguna incidencia/mantenimiento → resalta que hay actividad.
    """
    any_not_ok = any(not bool(v.get("overall_ok")) for v in vendors)
    counts = compute_counters(vendors)
    total_activity = counts["INC_NUEVOS_HOY"] + counts["INC_RESUELTOS_HOY"] + counts["MANTENIMIENTOS_HOY"]
    if not any_not_ok and total_activity == 0:
        return "Sin novedades relevantes."
    return "Actividad detectada en una o más plataformas. Revisar detalles por fabricante."

def next_report_date_utc_str() -> str:
    # Siguiente día (ISO corto)
    dt = datetime.now(timezone.utc) + timedelta(days=1)
    return dt.strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Construye digest_data.json para plantillas DORA")
    ap.add_argument("--vendors-dir", required=True, help="Directorio con JSON exportados por vendor")
    ap.add_argument("--out", required=True, help="Ruta de salida del JSON compuesto")
    args = ap.parse_args()

    # 1) Cargar vendors
    paths = sorted(glob.glob(os.path.join(args.vendors_dir, "*.json")))
    vendors: List[Dict[str, Any]] = []
    for p in paths:
        data = _read_json(p)
        if not data:
            continue
        # Normalizar claves esperadas
        v = {
            "name": data.get("name") or os.path.splitext(os.path.basename(p))[0],
            "timestamp_utc": data.get("timestamp_utc") or "",
            "component_lines": data.get("component_lines") or [],
            "incidents_lines": data.get("incidents_lines") or [],
            "overall_ok": bool(data.get("overall_ok")) if data.get("overall_ok") is not None else False,
        }
        vendors.append(v)

    # 2) Bloque Detalles por fabricante
    vendor_blocks = []
    for v in sorted(vendors, key=lambda x: (x.get("name") or "").lower()):
        vendor_blocks.append(build_vendor_block(v))
    detalles_por_vendor_texto = "\n\n".join(vendor_blocks).strip()

    # 3) Contadores + observación
    counts = compute_counters(vendors)
    obs_clave = build_obs_clave(vendors)

    # 4) Fuentes (HTML y TXT)
    html_src, txt_src = build_sources_blocks()

    # 5) Ventana de observación
    now_utc = datetime.now(timezone.utc)
    start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    ventana_utc = f"{start_utc.strftime('%Y-%m-%d 00:00')}–{now_utc.strftime('%Y-%m-%d %H:%M')}"

    # 6) Datos finales
    out_data: Dict[str, Any] = {
        # Meta
        "NUM_PROVEEDORES": len(vendors),
        "VENTANA_UTC": ventana_utc,
        # Detalles
        "DETALLES_POR_VENDOR_TEXTO": detalles_por_vendor_texto,
        # Contadores (aprox.)
        "INC_NUEVOS_HOY": counts["INC_NUEVOS_HOY"],
        "INC_ACTIVOS": counts["INC_ACTIVOS"],
        "INC_RESUELTOS_HOY": counts["INC_RESUELTOS_HOY"],
        "MANTENIMIENTOS_HOY": counts["MANTENIMIENTOS_HOY"],
        # Recomendaciones / cumplimiento
        "OBS_CLAVE": obs_clave,
        "IMPACTO_CLIENTE_SI_NO": "",         # lo decides tú si quieres sobrescribir en el workflow
        "ACCION_SUGERIDA": "",               # idem
        "FECHA_SIGUIENTE_REPORTE": next_report_date_utc_str(),
        # Fuentes (HTML para correo HTML; TXT para correo de texto / Telegram)
        "LISTA_FUENTES_CON_ENLACES": html_src,
        "LISTA_FUENTES_TXT": txt_src,
        # Compat: si las plantillas todavía tuvieran estas tablas, vaciarlas
        "TABLA_INCIDENTES_HOY": "",
        "TABLA_INCIDENTES_15D": "",
        # Por si tu plantilla TXT añade firma HTML (la dejamos vacía)
        "FIRMA_HTML": "",
    }

    # 7) Escribir salida
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    print(f"[digest-data] OK → {args.out} ({len(vendors)} vendors)")

if __name__ == "__main__":
    main()
