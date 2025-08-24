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
      - LISTA_FUENTES_TXT (TXT con URLs, como quieres)
  * Recomendaciones operativas (heurística autocontenida)

Este script NO envía nada; solo prepara datos para run_digest.py.
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
    """Devuelve (html_ul_items, txt_lines). TXT muestra URLs simples (como pediste)."""
    html = "".join(f'<li><a href="{url}">{label}</a></li>\n' for label, url in SOURCES)
    txt  = "\n".join(f"- {url}" for _, url in SOURCES)
    return html, txt

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

STATUS_RESOLVED_RE = re.compile(r"\bResolved\b", re.I)
STATUS_ANY_TODAY_RE = re.compile(
    r"\b(Investigating|Identified|Update|Mitigated|Monitoring|Degraded|Incident|Partial Outage|Major Outage)\b",
    re.I,
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
        out: List[str] = []
        for it in x:
            if isinstance(it, str):
                out.extend(it.splitlines())
        return [ln.rstrip() for ln in out]
    if isinstance(x, str):
        return x.splitlines()
    return []

def _fmt_timestamp(ts: str) -> str:
    """Adapta 'YYYY-MM-DD HH:MM' o ISO a 'YYYY-MM-DD HH:MM'."""
    if not ts:
        return ""
    s = ts.strip().replace("T", " ").replace("Z", "")
    m = re.match(r"^\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", s)
    return m.group(1) if m else s

def _title_for_vendor(name: str) -> str:
    n = (name or "").strip()
    low = n.lower()
    if low.startswith("netskope"):
        return "Netskope - Estado de Incidentes"
    if low.startswith("proofpoint"):
        return "Proofpoint - Estado de Incidentes"
    if low.startswith("qualys"):
        return "Qualys - Estado de Incidentes"
    if low.startswith("imperva"):
        return "Imperva - Status"
    if low.startswith("akamai") or "guardicore" in low:
        return "Akamai (Guardicore) - Status"
    if low.startswith("cyberark"):
        return "CyberArk Privilege Cloud - Status"
    if low.startswith("aruba"):
        return "Aruba Central - Status"
    if low.startswith("trend"):
        return "Trend Micro - Status"
    return f"{n} - Status"

# ---------------------------------------------------------------------------
# “Detalles por fabricante” (texto plano)
# ---------------------------------------------------------------------------

def build_vendor_block(v: Dict[str, Any]) -> str:
    """
    Espera:
      { name, timestamp_utc, component_lines: [..], incidents_lines: [..], overall_ok: bool }
    Devuelve bloque limpio y homogéneo (sin HTML).
    """
    name = v.get("name") or "Vendor"
    ts   = _fmt_timestamp(v.get("timestamp_utc", ""))

    comp_lines = _safe_lines(v.get("component_lines"))
    inc_lines  = _safe_lines(v.get("incidents_lines"))
    overall_ok = bool(v.get("overall_ok"))

    out: List[str] = []
    out.append(f"=== {name.upper()} ===")
    out.append(_title_for_vendor(name))
    if ts:
        out.append(f"{ts} UTC")
    out.append("")

    # Component status
    has_comp_header = any(re.search(r"^\s*Component status\s*$", ln, re.I) for ln in comp_lines)
    if not has_comp_header:
        out.append("Component status")
    if comp_lines:
        for ln in comp_lines:
            ln = ln.strip()
            if not ln:
                continue
            out.append(ln if ln.startswith(("-", "•")) else f"- {ln}")
    else:
        out.append("- All components Operational" if overall_ok else "- (no data)")

    # Incidents today
    out.append("")
    has_inc_header = any(re.search(r"^\s*Incidents today\s*$", ln, re.I) for ln in inc_lines)
    if not has_inc_header:
        out.append("Incidents today")
    if inc_lines:
        empty_acc = True
        for ln in inc_lines:
            if ln.strip():
                empty_acc = False
            out.append(ln.rstrip())
        if empty_acc:
            out.append("- No incidents reported today.")
    else:
        out.append("- No incidents reported today.")

    return "\n".join(out).rstrip()

# ---------------------------------------------------------------------------
# Contadores (aprox.) y heurística de recomendaciones
# ---------------------------------------------------------------------------

def compute_counters(vendors: List[Dict[str, Any]]) -> Dict[str, int]:
    nuevos = 0
    resueltos = 0
    activos = 0  # sin señal fiable, mantener 0
    mant = 0
    for v in vendors:
        for ln in _safe_lines(v.get("incidents_lines")):
            if STATUS_RESOLVED_RE.search(ln):
                resueltos += 1
            elif STATUS_ANY_TODAY_RE.search(ln):
                nuevos += 1
        for ln in _safe_lines(v.get("component_lines")):
            if UNDER_MAINT_RE.search(ln):
                mant += 1
    return {
        "INC_NUEVOS_HOY": nuevos,
        "INC_ACTIVOS": activos,
        "INC_RESUELTOS_HOY": resueltos,
        "MANTENIMIENTOS_HOY": mant,
    }

def build_recommendations(vendors: List[Dict[str, Any]], counts: Dict[str, int]) -> Tuple[str, str]:
    nuevos = counts.get("INC_NUEVOS_HOY", 0)
    resueltos = counts.get("INC_RESUELTOS_HOY", 0)
    mant = counts.get("MANTENIMIENTOS_HOY", 0)

    total_activity = nuevos + resueltos + mant
    if total_activity == 0:
        return ("No", "Monitorización habitual (sin acciones adicionales).")

    if mant > 0 and nuevos == 0 and resueltos == 0:
        return ("No (mantenimiento programado)", "Verificar ventanas y posibles impactos planificados; sin acciones adicionales salvo seguimiento programado.")

    if nuevos > 0:
        return ("Sí (potencial)", "Comunicación interna breve; monitorización reforzada; revisión de alertas SIEM/observabilidad; seguimiento con el/los fabricante(s) hasta resolución.")

    # Solo resueltos hoy
    if resueltos > 0 and nuevos == 0:
        return ("No (incidentes ya resueltos)", "Verificar normalización de servicios y evidencias de resolución; realizar revisión post-incidente si procede.")

    # Fallback defensivo
    return ("No", "Monitorización habitual.")

# ---------------------------------------------------------------------------
# OBS_CLAVE y auxiliares
# ---------------------------------------------------------------------------

def build_obs_clave(vendors: List[Dict[str, Any]], counts: Dict[str, int]) -> str:
    any_not_ok = any(not bool(v.get("overall_ok")) for v in vendors)
    total_activity = counts["INC_NUEVOS_HOY"] + counts["INC_RESUELTOS_HOY"] + counts["MANTENIMIENTOS_HOY"]
    if not any_not_ok and total_activity == 0:
        return "Sin novedades relevantes."
    if counts["INC_NUEVOS_HOY"] > 0:
        return "Incidencias en curso en una o más plataformas. Revisión recomendada."
    if counts["MANTENIMIENTOS_HOY"] > 0:
        return "Mantenimientos programados detectados en una o más plataformas."
    if counts["INC_RESUELTOS_HOY"] > 0:
        return "Incidentes resueltos hoy; verificar normalización de servicios."
    return "Actividad detectada; revisar detalle por fabricante."

def next_report_date_utc_str() -> str:
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
        v = {
            "name": data.get("name") or os.path.splitext(os.path.basename(p))[0],
            "timestamp_utc": data.get("timestamp_utc") or "",
            "component_lines": data.get("component_lines") or [],
            "incidents_lines": data.get("incidents_lines") or [],
            "overall_ok": bool(data.get("overall_ok")) if data.get("overall_ok") is not None else False,
        }
        vendors.append(v)

    # 2) Detalles por fabricante (texto)
    vendor_blocks = []
    for v in sorted(vendors, key=lambda x: (x.get("name") or "").lower()):
        vendor_blocks.append(build_vendor_block(v))
    detalles_por_vendor_texto = "\n\n".join(vendor_blocks).strip()

    # 3) Contadores + observación + recomendaciones
    counts = compute_counters(vendors)
    obs_clave = build_obs_clave(vendors, counts)
    impacto, accion = build_recommendations(vendors, counts)

    # 4) Fuentes
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
        # Observación + Recomendaciones
        "OBS_CLAVE": obs_clave,
        "IMPACTO_CLIENTE_SI_NO": impacto,
        "ACCION_SUGERIDA": accion,
        "FECHA_SIGUIENTE_REPORTE": next_report_date_utc_str(),
        # Fuentes
        "LISTA_FUENTES_CON_ENLACES": html_src,  # para HTML
        "LISTA_FUENTES_TXT": txt_src,           # para TXT (URLs)
        # Compatibilidad con plantillas antiguas
        "TABLA_INCIDENTES_HOY": "",
        "TABLA_INCIDENTES_15D": "",
        "FIRMA_HTML": "",
    }

    # 7) Escribir salida
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    print(f"[digest-data] OK → {args.out} ({len(vendors)} vendors)")

if __name__ == "__main__":
    main()
