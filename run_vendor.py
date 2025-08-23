#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import importlib
import json
import os
import traceback
from datetime import datetime, timezone

# Utilidades comunes existentes
try:
    from common.browser import make_driver  # asumes que ya existe en tu repo
except Exception:
    # Fallback ultra simple si no existe: levanta error claro
    def make_driver(headless: bool = True):
        raise RuntimeError("common/browser.py: make_driver() no disponible")

# Notificaciones existentes (tu módulo)
try:
    from common.notify import Notifier  # si tu notify expone una clase
except Exception:
    # Adaptador si tu notify.py usa funciones sueltas; ajusta si fuera necesario
    class Notifier:
        def __init__(self):
            pass
        def telegram(self, text: str):
            print("[telegram]", text)
        def teams(self, text: str, title: str = None):
            print("[teams]", title or "Status", text)

# Export y normalización para el digest
from common.digest_export import (
    ensure_dir, export_with_fallback, save_digest_json,
)

def parse_args():
    ap = argparse.ArgumentParser(
        description="Orquestador por vendor (scraping + notificación)."
    )
    ap.add_argument("--vendor", required=True, help="Nombre del vendor (directorio en vendors/)")
    ap.add_argument("--export-json", help="Ruta a JSON de salida para el digest (opcional)")
    ap.add_argument("--headless", action="store_true", help="Forzar headless en Selenium (si aplica)")
    ap.add_argument("--no-headless", action="store_true", help="Forzar con UI (debug)")
    ap.add_argument("--save-html", action="store_true", help="Guardar HTML temporal (si tu flujo lo usa)")
    ap.add_argument("--quiet", action="store_true", help="Reduce logs por consola")
    return ap.parse_args()

def call_vendor_run(mod, driver, notifier):
    """
    Llama a mod.run con la mejor coincidencia de firma:
    run(driver, notifier) -> run(driver) -> run()
    """
    if hasattr(mod, "run"):
        try:
            return mod.run(driver, notifier)
        except TypeError:
            try:
                return mod.run(driver)
            except TypeError:
                return mod.run()
    else:
        raise RuntimeError("El módulo del vendor no expone función run().")

def main():
    args = parse_args()
    vendor_name = args.vendor.strip().lower()

    # Import dinámico del vendor
    try:
        mod = importlib.import_module(f"vendors.{vendor_name}")
    except Exception as e:
        raise SystemExit(f"No se pudo importar vendors.{vendor_name}: {e}")

    headless = True
    if args.no_headless:
        headless = False
    elif args.headless:
        headless = True

    driver = None
    try:
        driver = make_driver(headless=headless)

        # 1) Ejecución normal del vendor (no cambies tu lógica existente)
        notifier = Notifier()
        try:
            call_vendor_run(mod, driver, notifier)
        except Exception as e:
            if not args.quiet:
                print(f"[{vendor_name}] run() lanzó excepción:\n{traceback.format_exc()}")

        # 2) Export JSON para el digest (opcional)
        if args.export_json:
            ensure_dir(os.path.dirname(args.export_json) or ".")
            try:
                data = export_with_fallback(mod, driver, vendor_name)
            except Exception:
                data = {
                    "vendor": vendor_name,
                    "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "error": "export_with_fallback_failed",
                    "traceback": traceback.format_exc()[:2000],  # truncamos para no hinchar artefactos
                }
            save_digest_json(args.export_json, data)

    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
