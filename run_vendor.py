# run_vendor.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import importlib
import os
import traceback
from datetime import datetime, timezone

from common.browser import make_driver
from common.digest_export import ensure_dir, export_with_fallback, save_digest_json

# Notificador; compatible si no existe clase
try:
    from common.notify import Notifier
except Exception:
    class Notifier:
        def telegram(self, text: str): pass
        def teams(self, text: str, title: str | None = None): pass

def _call_vendor_run(mod, driver, notifier):
    if not hasattr(mod, "run"):
        raise RuntimeError("El módulo del vendor no expone función run().")
    try:
        return mod.run(driver, notifier)
    except TypeError:
        try:
            return mod.run(driver)
        except TypeError:
            return mod.run()

def main():
    ap = argparse.ArgumentParser(description="Orquestador por vendor (scraping + notificación).")
    ap.add_argument("--vendor", required=True, help="Nombre del vendor (directorio en vendors/)")
    ap.add_argument("--export-json", help="Ruta a JSON para el digest (opcional)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--no-headless", action="store_true")
    ap.add_argument("--save-html", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    vendor = args.vendor.strip().lower()
    try:
        mod = importlib.import_module(f"vendors.{vendor}")
    except Exception as e:
        raise SystemExit(f"No se pudo importar vendors.{vendor}: {e}")

    # Variables para la captura
    os.environ["CURRENT_VENDOR"] = vendor
    os.environ.setdefault("DIGEST_OUT_DIR", ".github/out/vendors")

    headless = True
    if args.no_headless:
        headless = False
    elif args.headless:
        headless = True

    driver = None
    try:
        driver = make_driver(headless=headless)

        # 1) Ejecución normal (envía y CAPTURA si DIGEST_CAPTURE=1)
        try:
            _call_vendor_run(mod, driver, Notifier())
        except Exception:
            if not args.quiet:
                print(f"[{vendor}] run() lanzó excepción:\n{traceback.format_exc()}")

        # 2) Export JSON para el digest (consume la CAPTURA si existe)
        if args.export_json:
            ensure_dir(os.path.dirname(args.export_json) or ".")
            try:
                data = export_with_fallback(mod, driver, vendor)
            except Exception:
                data = {
                    "vendor": vendor,
                    "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "error": "export_with_fallback_failed",
                    "traceback": traceback.format_exc()[:2000],
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
