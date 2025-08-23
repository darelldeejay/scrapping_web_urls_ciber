#!/usr/bin/env python3
# scripts/build_digest_data.py
import os, json, glob
from datetime import datetime, timezone
from typing import Dict, Any, List

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

def build_counts(items: List[Dict[str, Any]]) -> Dict[str, str]:
    new_today = active = resolved_today = maint_today = 0
    for it in items:
        c = safe_get(it, ["counts"], {}) or {}
        new_today += int(c.get("new_today", 0) or 0)
        active += int(c.get("active", 0) or 0)
        resolved_today += int(c.get("resolved_today", 0) or 0)
        maint_today += int(c.get("maintenance_today", 0) or 0)
    return {
        "INC_NUEVOS_HOY": str(new_today),
        "INC_ACTIVOS": str(active),
        "INC_RESUELTOS_HOY": str(resolved_today),
        "MANTENIMIENTOS_HOY": str(maint_today),
    }

def build_sources(items: List[Dict[str, Any]]) -> str:
    links, seen = [], set()
    for it in items:
        for s in it.get("sources", []) or []:
            if s and s not in seen:
                seen.add(s); links.append(f"<li>{s}</li>")
    return "\n".join(links)

def build_vendor_text(items: List[Dict[str, Any]]) -> str:
    """
    Une el texto de cada vendor (tal cual fue enviado al canal) en un bloque.
    Formato:
      === VENDOR ===
      <texto>
    """
    blocks: List[str] = []
    for it in items:
        vendor = (it.get("vendor") or "").strip() or "vendor"
        block = (safe_get(it, ["text", "vendor_block"], "") or "").strip()
        if not block:
            # Si no hay bloque, dejamos constancia explícita:
            block = "No incidents reported today."
        blocks.append(f"=== {vendor.upper()} ===\n{block}")
    return "\n\n".join(blocks)

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendors-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    items = load_vendor_jsons(args.vendors_dir)
    now = datetime.now(timezone.utc)

    data: Dict[str, Any] = {
        "NUM_PROVEEDORES": str(len(items)) if items else "",
        "OBS_CLAVE": "",
        "LISTA_FUENTES_CON_ENLACES": build_sources(items),
        "FECHA_SIGUIENTE_REPORTE": (now.strftime("%Y-%m-%d")),
        # ⬇️ NUEVO: bloque concatenado por vendor
        "DETALLES_POR_VENDOR_TEXTO": build_vendor_text(items),
    }
    data.update(build_tables_html(items))
    data.update(build_counts(items))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
