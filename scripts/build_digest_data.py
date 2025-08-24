#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import argparse
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple

try:
    # Python 3.9+
    from zoneinfo import ZoneInfo
    TZ_MADRID = ZoneInfo("Europe/Madrid")
except Exception:
    TZ_MADRID = None  # fallback: tratamos como UTC si no existe

# ------------- Utilidades ------------- #

def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _list_vendor_files(vendors_dir: str) -> List[str]:
    if not os.path.isdir(vendors_dir):
        return []
    out = []
    for fn in os.listdir(vendors_dir):
        if fn.lower().endswith(".json"):
            out.append(os.path.join(vendors_dir, fn))
    return sorted(out)

def _as_list(x) -> List[str]:
    if not x:
        return []
    if isinstance(x, list):
        return [str(i) for i in x if str(i).strip()]
    return [str(x)]

def _norm_ts(ts: str) -> str:
    """Normaliza timestamps a 'YYYY-MM-DD HH:MM UTC' si vienen en ISO Z o sin sufijo."""
    if not ts:
        return ""
    s = ts.strip()
    # 2025-08-24T00:10:19Z -> 2025-08-24 00:10 UTC
    if "T" in s and s.endswith("Z"):
        s = s.replace("T", " ").replace("Z", "")
        m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", s)
        s = m.group(1) if m else s
        return f"{s} UTC"
    # Ya viene como 'YYYY-MM-DD HH:MM' => añade UTC si falta
    if re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$", s) and not s.endswith("UTC"):
        return f"{s} UTC"
    return s

def _today_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _parse_dt_from_line(line: str) -> datetime | None:
    """Intenta parsear 'YYYY-MM-DD HH:MM UTC' en una línea tipo '   Inicio: ... · Fin: ...'."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\s+UTC", line or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0).replace(" UTC",""), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _greeting_madrid(now_utc: datetime) -> str:
    if TZ_MADRID:
        now_mad = now_utc.astimezone(TZ_MADRID)
    else:
        now_mad = now_utc  # fallback
    h = now_mad.hour
    if 6 <= h < 12:
        return "Buenos días,"
    elif 12 <= h < 20:
        return "Buenas tardes,"
    else:
        return "Buenas noches,"

# ------------- Render de vendor (sin duplicaciones) ------------- #

def render_vendor_block(v: Dict[str, Any]) -> str:
    """
    Render compacto y sin duplicados:
    - No inyecta 'Component status' si no hay component_lines ni banner.
    - No inyecta 'Incidents today' automáticamente: usa incidents_lines tal cual.
    - Si hay 'banner', lo muestra como línea suelta.
    """
    lines: List[str] = []

    name = (v.get("name") or v.get("vendor") or "Vendor").strip()
    lines.append(f"=== {name.upper()} ===")

    title = (v.get("title") or v.get("header") or "").strip()
    if title:
        lines.append(title)

    ts = (v.get("timestamp_utc") or v.get("timestamp") or v.get("ts") or "").strip()
    if ts:
        lines.append(_norm_ts(ts))

    if len(lines) > 1:
        lines.append("")

    component_lines = _as_list(v.get("component_lines"))
    banner = (v.get("banner") or "").strip()

    if component_lines:
        lines.append("Component status")
        for cl in component_lines:
            cln = str(cl).replace("• ", "- ")
            if not (cln.startswith("-") or cln.startswith("–")):
                cln = "- " + cln
            lines.append(cln)
        lines.append("")
    elif banner:
        # Mostrar banner si existe (sin forzar cabecera 'Component status')
        btxt = banner if banner.lower().startswith("system status") else f"System status: {banner}"
        lines.append(btxt)
        lines.append("")

    incidents_lines = _as_list(v.get("incidents_lines"))
    if incidents_lines:
        for il in incidents_lines:
            lines.append(str(il).replace("• ", "- "))
    else:
        lines.append("- No incidents reported today.")

    return "\n".join(lines)

# ------------- Métricas simples ------------- #

def count_metrics(vendors: List[Dict[str, Any]]) -> Tuple[int, int, int]:
    """
    Devuelve (activos_total, resueltos_hoy_total, mantenimientos_hoy_total) de forma conservadora.
    - Activos: líneas NO vacías bajo una sección que contenga 'Incidentes activos' y que no sea 'No hay...'
    - Resueltos hoy: bajo secciones de resueltos con una línea 'Fin: YYYY-MM-DD ...' de HOY (UTC).
    - Mantenimiento: detectar 'Under Maintenance' en component_lines o incidents_lines.
    """
    activos = 0
    resueltos_hoy = 0
    mantenimientos = 0
    today = _today_utc_str()

    for v in vendors:
        inc = _as_list(v.get("incidents_lines"))
        comp = _as_list(v.get("component_lines"))

        # Activos (buscar bloque que empieza con 'Incidentes activos')
        i = 0
        while i < len(inc):
            line = inc[i].strip().lower()
            if "incidentes activos" in line or "active incidents" in line:
                i += 1
                # contar hasta un separador en blanco o hasta otra cabecera conocida
                while i < len(inc):
                    l = inc[i].strip()
                    low = l.lower()
                    if not l or "últimos 15 días" in low or "past incidents" in low or "resuelt" in low:
                        break
                    if not ("no hay incidentes" in low or "no incidents" in low):
                        activos += 1
                    i += 1
                break
            i += 1

        # Resueltos hoy (buscar líneas de fecha Fin: ... con la fecha de hoy)
        for i in range(len(inc)):
            l = inc[i]
            if "fin:" in l.lower():
                dt = _parse_dt_from_line(l)
                if dt and dt.astimezone(timezone.utc).strftime("%Y-%m-%d") == today:
                    resueltos_hoy += 1

        # Mantenimiento (heurística)
        text_all = " ".join(comp + inc).lower()
        if "under maintenance" in text_all or "maintenance" in text_all:
            # contar 1 por vendor con mantenimiento visible
            mantenimientos += 1

    return activos, resueltos_hoy, mantenimientos

# ------------- Fuentes ------------- #

DEFAULT_SOURCES = [
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
    # Texto plano (para .txt)
    txt_lines = [f"- {label} ({url})" for (label, url) in DEFAULT_SOURCES]
    txt_block = "\n".join(txt_lines)

    # HTML <li> (para plantilla HTML)
    li_lines = [f'<li><a href="{url}">{label}</a></li>' for (label, url) in DEFAULT_SOURCES]
    li_block = "\n".join(li_lines)
    return txt_block, li_block

# ------------- Main build ------------- #

def main():
    ap = argparse.ArgumentParser(description="Construye datos agregados para el digest DORA")
    ap.add_argument("--vendors-dir", required=True, help="Directorio con JSONs por vendor")
    ap.add_argument("--out", required=True, help="Ruta de salida del JSON agregado")
    args = ap.parse_args()

    # Cargar vendors
    files = _list_vendor_files(args.vendors_dir)
    vendors: List[Dict[str, Any]] = []
    for p in files:
        v = _read_json(p)
        if v:
            vendors.append(v)

    # Render de bloques por vendor (sin duplicaciones)
    vendor_blocks: List[str] = [render_vendor_block(v) for v in vendors]
    detalles_por_vendor_texto = "\n\n".join(vendor_blocks)

    # Métricas básicas
    activos, resueltos_hoy, mantenimientos = count_metrics(vendors)
    # 'Nuevos hoy' ≈ activos (conservador). Si prefieres 0, pon 0.
    nuevos_hoy = activos

    # Ventana de observación
    now_utc = datetime.now(timezone.utc)
    start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    ventana_utc = f"{start_utc.strftime('%Y-%m-%d 00:00')}–{now_utc.strftime('%Y-%m-%d %H:%M')}"

    # Saludo
    saludo = _greeting_madrid(now_utc)

    # Observación clave (simple)
    if activos > 0:
        obs = f"Se detectan incidentes activos en {activos} registr{'o' if activos==1 else 'os'}."
    elif resueltos_hoy > 0:
        obs = f"Se han resuelto {resueltos_hoy} incidente{sufijo(resueltos_hoy)} durante la ventana."
    else:
        obs = "Sin incidentes activos reportados."

    # Fuentes
    fuentes_txt, fuentes_html = build_sources_blocks()

    # Siguiente reporte (UTC -> fecha)
    fecha_sig = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")

    data_out: Dict[str, Any] = {
        # Campos usados por las plantillas
        "FECHA_UTC": now_utc.strftime("%Y-%m-%d"),
        "HORA_MUESTREO_UTC": now_utc.strftime("%H:%M"),
        "VENTANA_UTC": ventana_utc,
        "NUM_PROVEEDORES": str(len(vendors)),

        "INC_NUEVOS_HOY": str(nuevos_hoy),
        "INC_ACTIVOS": str(activos),
        "INC_RESUELTOS_HOY": str(resueltos_hoy),
        "MANTENIMIENTOS_HOY": str(mantenimientos),

        "OBS_CLAVE": obs,
        "SALUDO_LINEA": saludo,

        "DETALLES_POR_VENDOR_TEXTO": detalles_por_vendor_texto,

        # Fuentes (texto y HTML)
        "LISTA_FUENTES_URLS": "\n".join(line for line in fuentes_txt.splitlines() if line.strip()),
        "LISTA_FUENTES_CON_ENLACES": "\n".join(line for line in fuentes_html.splitlines() if line.strip()),

        # Recomendaciones (si no defines valores en otro sitio, se dejan vacíos)
        "IMPACTO_CLIENTE_SI_NO": "",
        "ACCION_SUGERIDA": "",
        "FECHA_SIGUIENTE_REPORTE": fecha_sig,

        # Campos que ya no usamos pero dejamos presentes (vacíos) por compatibilidad
        "TABLA_INCIDENTES_HOY": "",
        "TABLA_INCIDENTES_15D": "",
    }

    # Guardar
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)

    print(f"[ok] Escrito {args.out} con {len(vendors)} vendor(s).")

def sufijo(n: int) -> str:
    return "" if n == 1 else "s"

if __name__ == "__main__":
    main()
