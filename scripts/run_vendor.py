#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import importlib

# Fix sys.path para encontrar módulos desde cualquier ubicación
# Cuando se ejecuta scripts/run_vendor.py, Python necesita poder importar 'common'
script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)  # Subir un nivel de scripts/ a raíz
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Arranque Selenium
from common.browser import make_driver
from common.logger import setup_logging, get_logger
from common.utils import now_utc_str
from bs4 import BeautifulSoup  # por si algún vendor lo usa internamente

logger = get_logger(__name__)

def main():
    setup_logging()
    ap = argparse.ArgumentParser(description="Run single vendor or export JSON for digest")
    ap.add_argument("--vendor", required=True, help="nombre del vendor (slug): aruba, cyberark, ...")
    ap.add_argument("--export-json", help="ruta de salida JSON con resumen para digest")
    ap.add_argument("--headless", action="store_true", default=True)
    args = ap.parse_args()

    slug = args.vendor.strip().lower()
    driver = make_driver(headless=args.headless)

    # Carga módulo del vendor
    try:
        mod = importlib.import_module(f"vendors.{slug}")
    except Exception as e:
        driver.quit()
        raise SystemExit(f"No se pudo importar vendors.{slug}: {e}")

    # 1) Intentar collect() nativo del vendor
    data = None
    try:
        if hasattr(mod, "collect") and callable(getattr(mod, "collect")):
            data = mod.collect(driver)  # debe devolver dict estándar
    except Exception:
        data = None

    # 2) Fallback common
    if data is None:
        try:
            from common.fallback_collectors import get_collector
            fn = get_collector(slug)
        except Exception:
            fn = None
        if fn:
            try:
                data = fn(driver)
            except Exception:
                data = None

    # 3) Último recurso: mínimo
    if not isinstance(data, dict):
        data = {
            "name": slug.title(),
            "timestamp_utc": now_utc_str(),
            "component_lines": [],
            "incidents_lines": ["No incidents reported today"],
            "overall_ok": None,
        }

    driver.quit()

    # Normalización mínima
    for k in ("component_lines", "incidents_lines"):
        v = data.get(k)
        if isinstance(v, str):
            data[k] = [x for x in v.splitlines() if x.strip()]
        elif not isinstance(v, list):
            data[k] = []

    data.setdefault("name", slug.title())
    data.setdefault("timestamp_utc", now_utc_str())

    # Export JSON si lo piden
    if args.export_json:
        import json
        out = args.export_json
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        # Camino "run" clásico: pequeño resumen a stdout (no notifica)
        logger.info("[%s] %s UTC", data.get('name'), data.get('timestamp_utc'))
        for ln in (data.get("component_lines") or []):
            logger.info(ln)
        for ln in (data.get("incidents_lines") or []):
            logger.info(ln)

if __name__ == "__main__":
    main()
