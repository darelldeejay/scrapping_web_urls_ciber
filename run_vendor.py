#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import importlib
import json
import os
import argparse
from datetime import datetime, timezone

from common.browser import make_driver
from common.config import is_valid_slug


def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run single vendor or export JSON for digest")
    ap.add_argument("--vendor", required=True, help="vendor slug: aruba, cyberark, ...")
    ap.add_argument("--export-json", help="output JSON path for digest")
    ap.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="run Chrome headless (default: True); use --no-headless to show the browser",
    )
    args = ap.parse_args()

    slug = args.vendor.strip().lower()

    # Security: validate slug before using it in importlib / file paths
    if not is_valid_slug(slug):
        raise SystemExit(f"Invalid vendor slug: {slug!r}")

    driver = make_driver(headless=args.headless)

    # Load vendor module
    try:
        mod = importlib.import_module(f"vendors.{slug}")
    except Exception as e:
        driver.quit()
        raise SystemExit(f"No se pudo importar vendors.{slug}: {e}")

    # 1) Try vendor's own collect()
    data = None
    try:
        if hasattr(mod, "collect") and callable(getattr(mod, "collect")):
            data = mod.collect(driver)
    except Exception:
        data = None

    # 2) Fallback to common collector
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

    # 3) Last-resort minimal stub
    if not isinstance(data, dict):
        data = {
            "name": slug.title(),
            "timestamp_utc": now_utc_str(),
            "component_lines": [],
            "incidents_lines": ["No incidents reported today"],
            "overall_ok": None,
        }

    driver.quit()

    # Normalise list fields
    for k in ("component_lines", "incidents_lines"):
        v = data.get(k)
        if isinstance(v, str):
            data[k] = [x for x in v.splitlines() if x.strip()]
        elif not isinstance(v, list):
            data[k] = []

    data.setdefault("name", slug.title())
    data.setdefault("timestamp_utc", now_utc_str())

    if args.export_json:
        out = args.export_json
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        # Classic run path: print a brief summary to stdout (no notifications)
        print(f"[{data.get('name')}] {data.get('timestamp_utc')} UTC")
        for ln in (data.get("component_lines") or []):
            print(ln)
        for ln in (data.get("incidents_lines") or []):
            print(ln)


if __name__ == "__main__":
    main()
