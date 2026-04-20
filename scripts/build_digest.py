# build_digest.py
import os
import importlib
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape

from common.browser import start_driver
from common.notify import send_telegram, send_teams
from common.mailer import send_email_smtp

# Vendors a incluir en el digest (nombre -> módulo)
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
    # Presentación: YYYY-MM-DD HH:MM en horario Europa/Madrid
    # (sin dependencias extra; formato sin tzname)
    offset_cet = 1
    offset_cest = 2
    # Heurística simple DST: abril–octubre = CEST; resto CET (suficiente para presentación)
    month = dt_utc.month
    offset = offset_cest if 4 <= month <= 10 else offset_cet
    local = dt_utc.replace(tzinfo=timezone.utc).timestamp() + offset*3600
    local_dt = datetime.utcfromtimestamp(local)
    return local_dt.strftime("%Y-%m-%d %H:%M")

def load_templates():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"])
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
    Espera que cada vendor exporte collect(driver) -> dict con:
      {
        "name": "Vendor Name",
        "component_lines": [ ... ],
        "incidents_lines": [ ... ],
        "overall_ok": True/False
      }
    """
    mod = importlib.import_module(modname)
    if hasattr(mod, "collect"):
        return mod.collect(driver)
    # fallback muy básico: si no existe collect(), no romper
    return {
        "name": modname.split(".")[-1].capitalize(),
        "component_lines": ["(collector missing)"],
        "incidents_lines": ["No incidents reported today."],
        "overall_ok": False,
    }

def build_summary(vendors_data):
    total = len(vendors_data)
    ok = sum(1 for v in vendors_data if v.get("overall_ok"))
    attn = total - ok
    return {"vendors_total": total, "vendors_ok": ok, "vendors_attention": attn}

def render_outputs(vendors_data):
    email_tmpl, digest_tmpl = load_templates()
    now_utc = datetime.utcnow()
    ctx = {
        "title": "Daily Vendor Status",
        "generated_at_local": _dt_local_madrid(now_utc),
        "generated_at_utc": now_utc.strftime("%Y-%m-%d %H:%M UTC"),
        "vendors": vendors_data,
        "summary": build_summary(vendors_data),
    }
    html = email_tmpl.render(**ctx)
    text = None
    if digest_tmpl:
        text = digest_tmpl.render(**ctx)
    else:
        # fallback texto rápido si no hay digest.txt
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
    # 1) Email (Gmail SMTP) — usa secrets en GitHub
    subj = f"Daily Vendor Status — {datetime.utcnow().strftime('%Y-%m-%d')}"
    send_email_smtp(subject=subj, html_body=html_body, text_body=text_body)
    # 2) Telegram/Teams — digest texto
    send_telegram(text_body)
    send_teams(text_body)

def main():
    driver = start_driver()
    try:
        vendors_collected = []
        for name, modname in VENDORS.items():
            try:
                data = collect_from_vendor(modname, driver)
                # Asegura estructura y nombre visible
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
