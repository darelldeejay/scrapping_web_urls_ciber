# vendors/guardicore.py
# -*- coding: utf-8 -*-
"""
Akamai (Guardicore) — soporte dual:
- run(): tu ejecución clásica con Selenium + notificación (se mantiene intacta)
- collect(driver): reutiliza el mismo parseo para export JSON (sin notificar)
  y hace fallback a la API Statuspage si fallara el DOM.

Esto permite conservar todo tu trabajo previo y, a la vez, alimentar el digest
con datos correctos y estables.
"""

import os
import re
import time
import json
import traceback
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Tu browser/notify originales para run()
from common.browser import start_driver  # run() legacy
from common.notify import send_telegram, send_teams

# Helper para fallback vía Statuspage
try:
    from common.statuspage import build_statuspage_result  # nuevo helper
    _HAS_STATUSPAGE = True
except Exception:
    _HAS_STATUSPAGE = False

URL = "https://www.akamaistatus.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

DEGRADED_RE = re.compile(r"\bDegraded\b|\bDegraded Performance\b", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    # OJO: esto incluye " UTC" porque lo usabas en mensajes.
    # Para export JSON, usaremos _now_utc_clean() sin " UTC".
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _now_utc_clean():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    for _ in range(60):
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            body = ""
        text = collapse_ws(body)
        if ("past incidents" in text.lower()
            or "components" in text.lower()
            or "services" in text.lower()
            or NO_INCIDENTS_TODAY_RE.search(text)
            or OPERATIONAL_RE.search(text)
            or DEGRADED_RE.search(text)):
            return
        time.sleep(0.3)

# -------- Parseo de grupos/children en el mismo orden visual --------

def parse_component_groups(soup: BeautifulSoup):
    groups = []
    for g in soup.select(".component-container.is-group"):
        gname_el = g.select_one(".name")
        gname = collapse_ws(gname_el.get_text(" ", strip=True)) if gname_el else "Group"
        gstatus_el = g.select_one(".component-status")
        gstatus = collapse_ws(gstatus_el.get_text(" ", strip=True)) if gstatus_el else ""

        children = []
        for ch in g.select(".component-inner-container"):
            n_el = ch.select_one(".name, .component-name")
            cname = collapse_ws(n_el.get_text(" ", strip=True)) if n_el else ""
            s_el = ch.select_one(".component-status, .status")
            cstatus = collapse_ws(s_el.get_text(" ", strip=True)) if s_el else ""
            if not cname:
                continue
            if cname.lower() == gname.lower():
                continue
            children.append({"name": cname, "status": cstatus})

        groups.append({"name": gname, "status": gstatus, "children": children})
    return groups

# -------- Past Incidents: solo HOY --------

def today_header_strings():
    now = datetime.utcnow()
    with_zero = now.strftime("%b %d, %Y")
    no_zero  = with_zero.replace(" 0", " ")
    return {with_zero, no_zero}

def find_today_block(soup: BeautifulSoup):
    blocks = soup.select(".incidents-list .status-day, .status-day")
    if not blocks:
        return None, None
    candidates = today_header_strings()
    for day in blocks:
        date_el = day.select_one(".date, h3, h4")
        date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else ""
        if date_str in candidates:
            return day, date_str
    for day in blocks:
        if "today" in (day.get("class") or []):
            date_el = day.select_one(".date, h3, h4")
            date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else "Today"
            return day, date_str
    return None, None

def parse_incidents_today(soup: BeautifulSoup):
    day, date_str = find_today_block(soup)
    default_date = list(today_header_strings())[0]
    if not day:
        full = collapse_ws(soup.get_text(" ", strip=True))
        if NO_INCIDENTS_TODAY_RE.search(full):
            return {"date": default_date, "count": 0, "items": ["No incidents reported today."]}
        return {"date": default_date, "count": 0, "items": ["No incidents section found."]}

    if "no-incidents" in (day.get("class") or []):
        msg = day.get_text(" ", strip=True)
        m = NO_INCIDENTS_TODAY_RE.search(msg)
        text = m.group(0) if m else "No incidents reported today."
        return {"date": date_str, "count": 0, "items": [text]}

    lines = []
    for inc in day.select(".incident-container, .unresolved-incident, .incident"):
        title_el = inc.select_one(".incident-title a, .incident-title")
        title = collapse_ws(title_el.get_text(" ", strip=True)) if title_el else "Incident"
        updates = inc.select(".updates-container .update, .incident-update, .update")
        latest = updates[0] if updates else None
        status_word, time_text = "", ""
        if latest:
            st_el = latest.select_one("strong, .update-status, .update-title")
            tm_el = latest.select_one("small, time, .update-time")
            status_word = collapse_ws(st_el.get_text(" ", strip=True)) if st_el else ""
            time_text = collapse_ws(tm_el.get_text(" ", strip=True)) if tm_el else ""
        if status_word and time_text:
            lines.append(f"{status_word} — {title} ({time_text})")
        elif status_word:
            lines.append(f"{status_word} — {title}")
        else:
            lines.append(title)

    return {"date": date_str, "count": len(lines), "items": lines or ["(No details)"]}

# -------- Formato de salida para mensajes (legacy run) --------

def format_message(groups, today_inc):
    lines = [
        "Akamai (Guardicore) - Status",
        now_utc_str(),
        ""
    ]

    # Component status (compacto)
    for g in groups:
        children = g.get("children") or []
        if children:
            any_non_oper = any(not OPERATIONAL_RE.search((c.get("status") or "")) for c in children)
            if any_non_oper:
                lines.append(f"{g['name']}")
                for c in children:
                    cname = c["name"]
                    cstatus = c.get("status") or "Unknown"
                    lines.append(f"{cname} {cstatus}")
            else:
                lines.append(f"{g['name']} Operational")
        else:
            status = g.get("status") or "Unknown"
            lines.append(f"{g['name']} {status}")

    # Incidents today (SIEMPRE con encabezado)
    lines.append("")
    lines.append("Incidents today")
    if today_inc.get("count", 0) > 0:
        lines.extend(today_inc["items"])
    else:
        msg = (today_inc.get("items") or ["No incidents reported today."])[0]
        lines.append(msg)

    return "\n".join(lines)

# -------- NUEVO: collect() para export JSON (sin notificar) --------

def _to_component_lines_from_groups(groups):
    """
    Reutiliza tu lógica compacta para producir component_lines normalizados.
    """
    component_lines = []
    for g in groups or []:
        children = g.get("children") or []
        if children:
            any_non_oper = any(not OPERATIONAL_RE.search((c.get("status") or "")) for c in children)
            if any_non_oper:
                component_lines.append(f"{g['name']}")
                for c in children:
                    cname = c["name"]
                    cstatus = c.get("status") or "Unknown"
                    component_lines.append(f"- {cname} {cstatus}")
            else:
                component_lines.append(f"{g['name']} Operational")
        else:
            status = g.get("status") or "Unknown"
            component_lines.append(f"{g['name']} {status}")
    # compacta duplicados
    seen, out = set(), []
    for ln in component_lines:
        if ln not in seen:
            seen.add(ln); out.append(ln)
    return out

def _to_incidents_lines_from_today(today_inc):
    items = today_inc.get("items") or []
    if not items or today_inc.get("count", 0) == 0:
        return ["No incidents reported today."]
    # normaliza a bullets
    out = []
    for it in items:
        s = str(it).strip()
        out.append(s if s.startswith("- ") else f"- {s}")
    return out

def collect(driver):
    """
    1) Intenta tu parseo DOM (Selenium+BS) y devuelve dict normalizado.
    2) Si falla o queda vacío, usa fallback a Statuspage API (si disponible).
    """
    try:
        # --- Tu flujo DOM original, sin notificar ---
        try:
            driver.set_page_load_timeout(45)
        except Exception:
            pass

        try:
            driver.get(URL)
        except TimeoutException:
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass

        try:
            wait_for_page(driver)
        except Exception:
            pass

        soup = BeautifulSoup(driver.page_source, "lxml")
        groups = parse_component_groups(soup)
        today_inc = parse_incidents_today(soup)

        component_lines = _to_component_lines_from_groups(groups)
        incidents_lines = _to_incidents_lines_from_today(today_inc)

        overall_ok = (
            all("Operational" in ln for ln in component_lines) and
            incidents_lines == ["No incidents reported today."]
        )

        # Si conseguimos algo con sentido, devolvemos
        if component_lines or incidents_lines != ["No incidents reported today."]:
            return {
                "name": "Akamai (Guardicore)",
                "timestamp_utc": _now_utc_clean(),  # sin " UTC"; el digest lo añade
                "component_lines": component_lines,
                "incidents_lines": incidents_lines,
                "overall_ok": overall_ok,
            }

    except Exception:
        # seguimos al fallback
        pass

    # --- Fallback a Statuspage si está disponible ---
    if _HAS_STATUSPAGE:
        return build_statuspage_result("Akamai (Guardicore)", URL.rstrip("/"))

    # Último recurso: sin datos
    return {
        "name": "Akamai (Guardicore)",
        "timestamp_utc": _now_utc_clean(),
        "component_lines": [],
        "incidents_lines": ["No incidents reported today."],
        "overall_ok": None,
    }

# -------- Runner legacy (se mantiene) --------

def run():
    driver = start_driver()
    try:
        try:
            driver.set_page_load_timeout(45)
        except Exception:
            pass

        try:
            driver.get(URL)
        except TimeoutException:
            print("⏱️ Page load timed out — using partial DOM (window.stop()).")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass

        try:
            wait_for_page(driver)
        except Exception:
            print("⚠️ Could not confirm page readiness, proceeding with available DOM.")

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("akamai_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML saved to akamai_page_source.html")
            except Exception as e:
                print(f"Could not save HTML: {e}")

        soup = BeautifulSoup(html, "lxml")
        groups = parse_component_groups(soup)
        today_inc = parse_incidents_today(soup)

        msg = format_message(groups, today_inc)
        print("\n===== AKAMAI (GUARDICORE) =====")
        print(msg)
        print("================================\n")

        # Notificaciones legacy (tu camino anterior)
        send_telegram(msg)
        send_teams(msg)

    except Exception as e:
        short = f"{type(e).__name__}: {str(e)}"
        if len(short) > 300:
            short = short[:300] + "…"
        print(f"[guardicore] ERROR: {short}")
        traceback.print_exc()
        send_telegram(f"Akamai (Guardicore) - Monitor\nError: {short}")
        send_teams(f"❌ Akamai (Guardicore) - Monitor\nError: {short}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
