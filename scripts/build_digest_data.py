#!/usr/bin/env python3
# scripts/build_digest_data.py
import os, json, glob
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

# Palabras “críticas” (para recomendar escalar). Ojo: sin 'impact' ni 'partial' genérico.
KEYWORDS_CRITICAL = (
    "critical", "major", "sev-1", "sev1", "p1", "security incident",
    "security advisory", "outage", "total outage", "unavailable", "ddos", "breach"
)

def load_vendor_jsons(vendors_dir: str) -> List[Dict[str, Any]]:
    paths = sorted(glob.glob(os.path.join(vendors_dir, "*.json")))
    items = []
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    items.append(data)
        except Exception:
            continue
    return items

def safe_get(d: Dict[str, Any], path: List[str], default=None):
    cur = d
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur

def build_tables_html(items: List[Dict[str, Any]]) -> Dict[str, str]:
    rows_today, rows_15d = [], []
    for it in items:
        t_today = safe_get(it, ["tables", "today_rows_html"], "")
        t_15d = safe_get(it, ["tables", "past15_rows_html"], "")
        if t_today: rows_today.append(t_today.strip())
        if t_15d: rows_15d.append(t_15d.strip())
    return {
        "FILAS_INCIDENTES_HOY": "\n".join(rows_today),
        "FILAS_INCIDENTES_15D": "\n".join(rows_15d),
    }

def build_counts(items: List[Dict[str, Any]]) -> Dict[str, int]:
    new_today = active = resolved_today = maint_today = 0
    for it in items:
        c = safe_get(it, ["counts"], {}) or {}
        new_today += int(c.get("new_today", 0) or 0)
        active += int(c.get("active", 0) or 0)
        resolved_today += int(c.get("resolved_today", 0) or 0)
        maint_today += int(c.get("maintenance_today", 0) or 0)
    return {
        "INC_NUEVOS_HOY": new_today,
        "INC_ACTIVOS": active,
        "INC_RESUELTOS_HOY": resolved_today,
        "MANTENIMIENTOS_HOY": maint_today,
    }

def build_sources(items: List[Dict[str, Any]]) -> str:
    links, seen = [], set()
    for it in items:
        for s in it.get("sources", []) or []:
            if s and s not in seen:
                seen.add(s); links.append(f"<li>{s}</li>")
    return "\n".join(links)

def build_vendor_text(items: List[Dict[str, Any]]) -> str:
    blocks: List[str] = []
    for it in items:
        vendor = (it.get("vendor") or "").strip() or "vendor"
        block = (safe_get(it, ["text", "vendor_block"], "") or "").strip()
        if not block:
            block = "No incidents reported today."
        blocks.append(f"=== {vendor.upper()} ===\n{block}")
    return "\n\n".join(blocks)

def infer_operational_recommendations(items: List[Dict[str, Any]], counts: Dict[str, int]) -> Dict[str, str]:
    """
    Regla clara:
      - Si INC_ACTIVOS == 0 → Impacto=No, Acción=Sin acción.
      - Si INC_ACTIVOS > 0 y hay palabras críticas → Impacto=Sí (potencialmente crítico), Acción=Escalar...
      - Si INC_ACTIVOS > 0 y no crítico → Impacto=Posible, Acción=Monitorización...
    """
    active = counts.get("INC_ACTIVOS", 0)
    if active <= 0:
        return {
            "IMPACTO_CLIENTE_SI_NO": "No",
            "ACCION_SUGERIDA": "Sin acción."
        }

    any_critical = False
    for it in items:
        txt = (safe_get(it, ["text", "vendor_block"], "") or "")
        low = txt.lower()
        if any(k in low for k in KEYWORDS_CRITICAL):
            any_critical = True
            break

    if any_critical:
        return {
            "IMPACTO_CLIENTE_SI_NO": "Sí (potencialmente crítico)",
            "ACCION_SUGERIDA": "Escalar a proveedor/es y comunicación interna; monitorización reforzada hasta resolución."
        }
    return {
        "IMPACTO_CLIENTE_SI_NO": "Posible",
        "ACCION_SUGERIDA": "Monitorización reforzada y verificación de servicios dependientes."
    }

def compute_next_review_date_str() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

def load_overrides(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: ("" if v is None else str(v)) for k, v in data.items()}
    except Exception:
        return {}

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendors-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--overrides", help="JSON con campos que sobrescriben (IMPACTO_CLIENTE_SI_NO, ACCION_SUGERIDA, FECHA_SIGUIENTE_REPORTE)")
    args = ap.parse_args()

    items = load_vendor_jsons(args.vendors_dir)
    counts = build_counts(items)

    data: Dict[str, Any] = {
        "NUM_PROVEEDORES": str(len(items)) if items else "0",
        "OBS_CLAVE": "",
        "LISTA_FUENTES_CON_ENLACES": build_sources(items),
        "FECHA_SIGUIENTE_REPORTE": compute_next_review_date_str(),
        "DETALLES_POR_VENDOR_TEXTO": build_vendor_text(items),
        "FILAS_INCIDENTES_HOY": "",
        "FILAS_INCIDENTES_15D": "",
        "INC_NUEVOS_HOY": str(counts["INC_NUEVOS_HOY"]),
        "INC_ACTIVOS": str(counts["INC_ACTIVOS"]),
        "INC_RESUELTOS_HOY": str(counts["INC_RESUELTOS_HOY"]),
        "MANTENIMIENTOS_HOY": str(counts["MANTENIMIENTOS_HOY"]),
    }

    tables = build_tables_html(items)
    data.update(tables)

    # Recomendaciones (con la regla de “si no hay activos => No/Sin acción”)
    recs = infer_operational_recommendations(items, counts)
    data.update(recs)

    # Overrides manuales (si vienen)
    overrides = load_overrides(args.overrides)
    data.update({k: v for k, v in overrides.items() if v is not None})

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
