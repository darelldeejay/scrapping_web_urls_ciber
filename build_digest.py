# build_digest.py
# -*- coding: utf-8 -*-
"""
DEPRECATED — Legacy all-in-one digest builder.

This file is kept only for historical reference and is NOT used by the
production workflow (see .github/workflows/status-check.yml).

The active production pipeline is:
  run_vendor.py  →  scripts/build_digest_data.py  →  run_digest.py

Known issues (do not attempt to fix here; use the pipeline above):
  - ``from common.mailer import send_email_smtp`` will fail at import time
    because ``common/mailer.py`` does not exist.
  - Relies on Jinja2 templates that may not match the current template names.
"""

import importlib
import warnings
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader, select_autoescape

from common.browser import start_driver

# Graceful import of notification helpers — they may have changed signatures
try:
    from common.notify import send_telegram, send_teams
except ImportError:
    send_telegram = None  # type: ignore[assignment]
    send_teams = None  # type: ignore[assignment]

# common/mailer.py does not exist; wrap the import so the module can at least
# be imported without immediately crashing other tooling that inspects it.
try:
    from common.mailer import send_email_smtp  # type: ignore[import]
except ImportError:
    def send_email_smtp(*args, **kwargs):  # type: ignore[misc]
        raise NotImplementedError(
            "common/mailer.py does not exist. "
            "Use run_digest.py (Telegram/Teams) for notifications."
        )

warnings.warn(
    "build_digest.py is deprecated and broken. "
    "Use the run_vendor.py → scripts/build_digest_data.py → run_digest.py pipeline instead.",
    DeprecationWarning,
    stacklevel=1,
)

# Vendors to include in the digest (name -> module)
VENDORS = {
    "Netskope":   "vendors.netskope",
    "Proofpoint": "vendors.proofpoint",
    "Qualys":     "vendors.qualys",
    "Aruba":      "vendors.aruba",
    "Imperva":    "vendors.imperva",
    "CyberArk":   "vendors.cyberark",
    "Trend Micro": "vendors.trendmicro",
    "Akamai (Guardicore)": "vendors.guardicore",
}


def _dt_local_madrid(dt_utc: datetime) -> str:
    """Return a human-readable Madrid-local datetime string (heuristic DST)."""
    # Heuristic: April–October = CEST (+2), otherwise CET (+1)
    offset = 2 if 4 <= dt_utc.month <= 10 else 1
    local = dt_utc.replace(tzinfo=timezone.utc).timestamp() + offset * 3600
    local_dt = datetime.utcfromtimestamp(local)
    return local_dt.strftime("%Y-%m-%d %H:%M")


def load_templates():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
    )
    email_tmpl = env.get_template("email.html")
    digest_tmpl = None
    try:
        digest_tmpl = env.get_template("digest.txt")
    except Exception:
        pass
    return email_tmpl, digest_tmpl


def collect_from_vendor(modname: str, driver):
    """
    Expects each vendor to export collect(driver) -> dict with::

        {
            "name": str,
            "component_lines": list[str],
            "incidents_lines": list[str],
            "overall_ok": bool,
        }
    """
    mod = importlib.import_module(modname)
    if hasattr(mod, "collect"):
        return mod.collect(driver)
    # Graceful fallback: if collect() is missing, return a placeholder
    return {
        "name": modname.split(".")[-1].capitalize(),
        "component_lines": ["(collector missing)"],
        "incidents_lines": ["No incidents reported today."],
        "overall_ok": False,
    }


def build_summary(vendors_data):
    total = len(vendors_data)
    ok = sum(1 for v in vendors_data if v.get("overall_ok"))
    return {"vendors_total": total, "vendors_ok": ok, "vendors_attention": total - ok}


def render_outputs(vendors_data):
    email_tmpl, digest_tmpl = load_templates()
    now_utc = datetime.now(timezone.utc)
    ctx = {
        "title": "Daily Vendor Status",
        "generated_at_local": _dt_local_madrid(now_utc),
        "generated_at_utc": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        "vendors": vendors_data,
        "summary": build_summary(vendors_data),
    }
    html = email_tmpl.render(**ctx)
    if digest_tmpl:
        text = digest_tmpl.render(**ctx)
    else:
        lines = [f"{ctx['title']} — {ctx['generated_at_utc']}", ""]
        for v in vendors_data:
            lines.append(f"## {v['name']}")
            lines.extend(f"- {ln}" for ln in v["component_lines"])
            lines.append("Incidents today")
            lines.extend(f"- {ln}" for ln in v["incidents_lines"])
            lines.append("")
        text = "\n".join(lines)
    return html, text


def send_outputs(html_body: str, text_body: str):
    subj = f"Daily Vendor Status — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    send_email_smtp(subject=subj, html_body=html_body, text_body=text_body)
    if send_telegram:
        send_telegram(text_body)
    if send_teams:
        send_teams(text_body)


def main():
    driver = start_driver()
    try:
        vendors_collected = []
        for name, modname in VENDORS.items():
            try:
                data = collect_from_vendor(modname, driver)
                data["name"] = data.get("name") or name
                data["component_lines"] = data.get("component_lines") or []
                data["incidents_lines"] = data.get("incidents_lines") or ["No incidents reported today."]
                data["overall_ok"] = bool(data.get("overall_ok"))
                vendors_collected.append(data)
            except Exception as e:
                vendors_collected.append({
                    "name": name,
                    "component_lines": [f"(error collecting: {e})"],
                    "incidents_lines": ["No incidents reported today."],
                    "overall_ok": False,
                })

        html, text = render_outputs(vendors_collected)
        send_outputs(html, text)
        print("Digest built and sent.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
