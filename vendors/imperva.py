# vendors/imperva.py
# -*- coding: utf-8 -*-
"""
Imperva — soporte dual:
- run(): tu ejecución clásica con Selenium + notificación (se mantiene)
- collect(driver): reutiliza tu parseo para export JSON (sin notificar)
  y hace fallback a la API Statuspage si el DOM cambia.

Salida normalizada para el digest:
- name: "Imperva"
- timestamp_utc: "YYYY-MM-DD HH:MM"  (sin sufijo "UTC")
- component_lines: ["All components Operational"] o ["Nombre: Status [POPs: ...]", ...]
- incidents_lines: ["No incidents reported today."] o viñetas "- ..."
- overall_ok: True si no hay incidentes hoy y todos los componentes están OK
"""

import os
import re
import time
import traceback
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams

# Fallback a Statuspage (opcional)
try:
    from common.statuspage import build_statuspage_result
    _HAS_STATUSPAGE = True
except Exception:
    _HAS_STATUSPAGE = False

URL = "https://status.imperva.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# Estados problemáticos típicos (Statuspage)
ISSUE_STATUS_RE = re.compile(r"(Degraded Performance|Partial Outage|Major Outage|Under Maintenance)", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    # Para mensajes legacy (con sufijo "UTC")
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _now_utc_clean():
    # Para export JSON (el digest añade 'UTC' al render)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    # Espera a que cargue texto relevante de componentes o incidents
    for _ in range(40):
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            body = ""
        text = collapse_ws(body)
        if ("components" in text.lower()
            or "incidents" in text.lower()
            or NO_INCIDENTS_TODAY_RE.search(text)
            or OPERATIONAL_RE.search(text)
            or ISSUE_STATUS_RE.search(text)):
            return
        time.sleep(0.5)

# ---------- POPs (heurística) ----------

POP_HINTS = re.compile(
    r"\b(POP|PoP|Point of Presence|Location\(s\)|Locations|Region\(s\)|Regions|Datacenter|Data Center|Edge|CDN)\b",
    re.I,
)
POP_CODE = re.compile(r"\b[A-Z0-9]{3,5}\b")
BLACKLIST = {"HTTP", "HTTPS", "CDN", "DNS", "WAF", "API", "EDGE", "CACHE", "SITE", "DATA", "CENTER", "INC"}

def extract_pops_from_text(text: str):
    if not text:
        return []
    lines = [collapse_ws(x) for x in text.splitlines() if collapse_ws(x)]
    pops = set()
    for ln in lines:
        if POP_HINTS.search(ln) or "pop" in ln.lower():
            m = re.search(r"(?:POP[s]?:?|Location[s]?:?|Region[s]?:?)\s*([A-Z0-9,\s/;:-]+)", ln, flags=re.I)
            if m:
                chunk = collapse_ws(m.group(1))
                for token in re.split(r"[,\s/;:-]+", chunk):
                    tok = token.strip().upper()
                    if POP_CODE.fullmatch(tok) and tok not in BLACKLIST:
                        pops.add(tok)
            for m2 in POP_CODE.finditer(ln):
                tok = m2.group(0).upper()
                if tok not in BLACKLIST:
                    pops.add(tok)
    return sorted(pops)[:12]

def extract_pops_from_component(comp):
    pops = set()
    for li in comp.select("li"):
        t = collapse_ws(li.get_text(" ", strip=True))
        for m in POP_CODE.finditer(t):
            tok = m.group(0).upper()
            if tok not in BLACKLIST:
                pops.add(tok)
    for tag in comp.select("span, div, a"):
        t = collapse_ws(tag.get_text(" ", strip=True))
        if 3 <= len(t) <= 5 and t.isupper() and t not in BLACKLIST and POP_CODE.fullmatch(t):
            pops.add(t)
    return sorted(pops)[:12]

# ---------- Componentes (solo no-operational) ----------

def parse_components(soup: BeautifulSoup):
    """
    Devuelve lista de dicts:
      { "name": "...", "status": "Degraded Performance", "pops": [ ... ] }
    Solo para componentes NO 'Operational'. Si el comp es un grupo de 'EMEA PoPs', intenta sacar los POPs hijos.
    """
    results = []
    cards = soup.select(".components-section .component-inner-container")
    if not cards:
        for tag in soup.find_all(True):
            txt = collapse_ws(getattr(tag, "get_text", lambda *a, **k: "")(" ", strip=True))
            m = ISSUE_STATUS_RE.search(txt)
            if m:
                pos = txt.lower().find(m.group(1).lower())
                name = collapse_ws(txt[:pos]) if pos > 0 else "Component"
                results.append({"name": name, "status": m.group(1), "pops": []})
        uniq, seen = [], set()
        for it in results:
            key = (it["name"].lower(), it["status"].lower())
            if key not in seen:
                seen.add(key); uniq.append(it)
        return uniq

    for comp in cards:
        status_attr = (comp.get("data-component-status") or "").strip().lower()
        name_el = comp.select_one(".name, .component-name, [data-component-name]")
        status_text_el = comp.select_one(".component-status, .status")
        name = None
        if name_el:
            name = collapse_ws(name_el.get_text(" ", strip=True))
        if not name and comp.has_attr("data-component-name"):
            name = collapse_ws(comp["data-component-name"])
        name = name or "Component"
        status_text = collapse_ws(status_text_el.get_text(" ", strip=True)) if status_text_el else (status_attr or "Unknown")

        if status_attr == "operational":
            continue
        if not status_attr and OPERATIONAL_RE.search(status_text):
            continue
        if OPERATIONAL_RE.search(status_text):
            continue

        pops = []
        if re.search(r"\b(POPs?|EMEA|AMER|APAC|EU|EUROPE|ASIA|AMERICA)\b", name, re.I):
            pops = extract_pops_from_component(comp)
            if not pops:
                pops = extract_pops_from_text(collapse_ws(comp.get_text(" ", strip=True)))

        results.append({"name": name, "status": status_text, "pops": pops})

    uniq, seen = [], set()
    for it in results:
        key = (it["name"].lower(), it["status"].lower(), tuple(it.get("pops") or []))
        if key not in seen:
            seen.add(key); uniq.append(it)
    return uniq

# ---------- Incidentes: SOLO el día actual ----------

def today_header_strings():
    now = datetime.utcnow()
    with_zero = now.strftime("%b %d, %Y")
    no_zero  = with_zero.replace(" 0", " ")
    return {with_zero, no_zero}

def find_today_day_block(soup: BeautifulSoup):
    day_blocks = soup.select(".incidents-list .status-day")
    if not day_blocks:
        return None, None
    candidates = today_header_strings()
    for day in day_blocks:
        date_el = day.select_one(".date, h3, h4")
        date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else ""
        if date_str in candidates:
            return day, date_str
    for day in day_blocks:
        if "today" in (day.get("class") or []):
            date_el = day.select_one(".date, h3, h4")
            date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else "Today"
            return day, date_str
    return None, None

def parse_incidents_today(soup: BeautifulSoup):
    day, date_str = find_today_day_block(soup)
    default_date = list(today_header_strings())[0]
    if not day:
        full = collapse_ws(soup.get_text(" ", strip=True))
        if NO_INCIDENTS_TODAY_RE.search(full):
            return {"date": default_date, "count": 0, "items": ["- No incidents reported today."]}
        return {"date": default_date, "count": 0, "items": ["- No incidents section found."]}

    if "no-incidents" in (day.get("class") or []):
        msg = day.get_text(" ", strip=True)
        m = NO_INCIDENTS_TODAY_RE.search(msg)
        text = m.group(0) if m else "No incidents reported today."
        return {"date": date_str, "count": 0, "items": [f"- {text}"]}

    items = []
    for inc in day.select(".incident-container, .unresolved-incident"):
        title_el = inc.select_one(".incident-title a, .incident-title")
        title = collapse_ws(title_el.get_text(" ", strip=True)) if title_el else "Incident"
        updates = inc.select(".updates-container .update, .incident-update")
        latest = updates[0] if updates else None
        status_word, time_text = "", ""
        if latest:
            st_el = latest.select_one("strong, .update-status, .update-title")
            tm_el = latest.select_one("small, time, .update-time")
            status_word = collapse_ws(st_el.get_text(" ", strip=True)) if st_el else ""
            time_text = collapse_ws(tm_el.get_text(" ", strip=True)) if tm_el else ""

        pops = extract_pops_from_text(collapse_ws(inc.get_text(" ", strip=True)))
        if not pops and latest:
            pops = extract_pops_from_text(collapse_ws(latest.get_text(" ", strip=True)))
        pop_suffix = f" [POPs: {', '.join(pops)}]" if pops else ""

        if status_word and time_text:
            items.append(f"{status_word} — {title} ({time_text}){pop_suffix}")
        elif status_word:
            items.append(f"{status_word} — {title}{pop_suffix}")
        else:
            items.append(f"{title}{pop_suffix}")

    return {"date": date_str, "count": len(items), "items": items or ["- (No details)"]}

# ---------- Formato mensaje (legacy) ----------

def format_message(components, today_inc):
    lines = [
        "Imperva - Status",
        now_utc_str(),
        ""
    ]

    # Overall status (tranquilidad)
    overall_bits = []
    if not components:
        overall_bits.append("All components Operational")
    if today_inc and (today_inc.get("count", 0) == 0):
        items = today_inc.get("items") or []
        literal = next((it for it in items if "No incidents reported today" in it), None)
        overall_bits.append(literal or "No incidents reported today.")
    if overall_bits:
        lines.append("Overall status: " + " • ".join(overall_bits))
        lines.append("")

    # Component status (only non-operational)
    lines.append("Component status")
    if components:
        for it in components:
            suffix = f" [POPs: {', '.join(it['pops'])}]" if it.get("pops") else ""
            lines.append(f"- {it['name']}: {it['status']}{suffix}")
    else:
        lines.append("- All components Operational")

    # Incidents today
    lines.append("")
    if today_inc.get("count", 0) > 0:
        lines.append(f"Incidents today — {today_inc['count']} incident(s)")
    else:
        lines.append("Incidents today")
    for line in (today_inc.get("items") or ["- No incidents reported today."]):
        lines.append(line)

    return "\n".join(lines)

# ---------- NUEVO: collect() para export JSON (sin notificar) ----------

def collect(driver):
    """
    1) Intenta tu parseo DOM (Selenium+BS) y devuelve dict normalizado.
    2) Si falla o queda vacío, usa fallback a Statuspage API (si disponible).
    """
    try:
        driver.get(URL)
        wait_for_page(driver)

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("imperva_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass

        soup = BeautifulSoup(html, "lxml")
        comps = parse_components(soup)
        today_inc = parse_incidents_today(soup)

        # component_lines
        if comps:
            component_lines = []
            for it in comps:
                suffix = f" [POPs: {', '.join(it['pops'])}]" if it.get("pops") else ""
                component_lines.append(f"{it['name']}: {it['status']}{suffix}")
        else:
            component_lines = ["All components Operational"]

        # incidents_lines
        items = today_inc.get("items") or []
        incidents_lines = []
        if not items:
            incidents_lines = ["No incidents reported today."]
        else:
            for t in items:
                t = str(t).lstrip("• ").strip()
                incidents_lines.append(t if t.startswith("- ") else f"- {t}")
            if incidents_lines == ["- No incidents reported today."]:
                incidents_lines = ["No incidents reported today."]

        overall_ok = (component_lines == ["All components Operational"] and
                      incidents_lines == ["No incidents reported today."])

        # Si hay algo útil, devolvemos
        if component_lines or incidents_lines != ["No incidents reported today."]:
            return {
                "name": "Imperva",
                "timestamp_utc": _now_utc_clean(),
                "component_lines": component_lines,
                "incidents_lines": incidents_lines,
                "overall_ok": overall_ok,
            }

    except Exception:
        # seguimos al fallback
        pass

    # --- Fallback a Statuspage si está disponible ---
    if _HAS_STATUSPAGE:
        return build_statuspage_result("Imperva", URL.rstrip("/"))

    # Último recurso
    return {
        "name": "Imperva",
        "timestamp_utc": _now_utc_clean(),
        "component_lines": [],
        "incidents_lines": ["No incidents reported today."],
        "overall_ok": None,
    }

# ---------- Runner (legacy con notificaciones) ----------

def run():
    driver = start_driver()
    try:
        driver.get(URL)
        wait_for_page(driver)

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("imperva_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML saved to imperva_page_source.html")
            except Exception as e:
                print(f"Could not save HTML: {e}")

        soup = BeautifulSoup(html, "lxml")
        comps = parse_components(soup)
        today_inc = parse_incidents_today(soup)

        msg = format_message(comps, today_inc)
        print("\n===== IMPERVA =====")
        print(msg)
        print("===================\n")

        send_telegram(msg)
        send_teams(msg)

    except Exception as e:
        print(f"[imperva] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"Imperva - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ Imperva - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
