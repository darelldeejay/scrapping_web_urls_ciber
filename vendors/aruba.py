# vendors/aruba.py
# -*- coding: utf-8 -*-
"""
Aruba Central — soporte dual:
- run(): tu ejecución clásica con Selenium + notificación (se mantiene)
- collect(driver): reutiliza tu parseo para export JSON (sin notificar)
  y hace fallback a la API Statuspage si el DOM falla.

Así conservas toda la depuración previa y el digest recibe datos correctos.
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

# Camino legacy de notificación
from common.browser import start_driver
from common.notify import send_telegram, send_teams

# Helper para fallback vía Statuspage (opcional)
try:
    from common.statuspage import build_statuspage_result
    _HAS_STATUSPAGE = True
except Exception:
    _HAS_STATUSPAGE = False

URL = "https://centralstatus.arubanetworking.hpe.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# Regex helpers
ISSUE_STATUS_RE = re.compile(r"(Degraded Performance|Partial Outage|Major Outage|Under Maintenance)", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    # Mensajes legacy
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _now_utc_clean():
    # Para export JSON (el digest añade 'UTC')
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    # Espera a que aparezca sección de componentes o texto de incidentes
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

def parse_components(soup: BeautifulSoup):
    """
    Devuelve lista de (name, status_text) SOLO para componentes NO 'Operational'.
    """
    results = []
    cards = soup.select(".components-section .component-inner-container")
    if not cards:
        # Fallback genérico: cualquier bloque con un estado problemático
        for tag in soup.find_all(True):
            txt = collapse_ws(getattr(tag, "get_text", lambda *a, **k: "")(" ", strip=True))
            m = ISSUE_STATUS_RE.search(txt)
            if m:
                pos = txt.lower().find(m.group(1).lower())
                name = collapse_ws(txt[:pos]) if pos > 0 else "Component"
                results.append((name, m.group(1)))
    else:
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
            # Solo reportar si NO es operational
            if status_attr and status_attr == "operational":
                continue
            if not status_attr and OPERATIONAL_RE.search(status_text):
                continue
            if not OPERATIONAL_RE.search(status_text):
                results.append((name, status_text))

    # dedup conservando orden
    uniq, seen = [], set()
    for name, st in results:
        key = (name.lower(), st.lower())
        if key not in seen:
            seen.add(key)
            uniq.append((name, st))
    return uniq

def parse_incidents_today(soup: BeautifulSoup):
    """
    Busca el bloque del día actual en la lista de incidents.
    Si hay 'No incidents reported today.', lo devuelve; si hay incidentes,
    lista el último estado de cada incidente (status word + timestamp) con el título.
    """
    day_block = soup.select_one(".incidents-list .status-day")
    if not day_block:
        full_text = collapse_ws(soup.get_text(" ", strip=True))
        if NO_INCIDENTS_TODAY_RE.search(full_text):
            return {"no_incidents": True, "items": ["No incidents reported today."]}
        return {"no_incidents": False, "items": []}

    classes = day_block.get("class", [])
    if "no-incidents" in classes:
        msg = day_block.get_text(" ", strip=True)
        m = NO_INCIDENTS_TODAY_RE.search(msg)
        text = m.group(0) if m else "No incidents reported today."
        return {"no_incidents": True, "items": [text]}

    # Hay incidentes en ese día
    items = []
    for inc in day_block.select(".incident-container"):
        title_el = inc.select_one(".incident-title a, .incident-title")
        title = collapse_ws(title_el.get_text(" ", strip=True)) if title_el else "Incident"
        updates = inc.select(".updates-container .update")
        latest = updates[0] if updates else None
        if latest:
            st_el = latest.select_one("strong")
            tm_el = latest.select_one("small")
            status_word = collapse_ws(st_el.get_text(" ", strip=True)) if st_el else ""
            time_text = collapse_ws(tm_el.get_text(" ", strip=True)) if tm_el else ""
            if status_word and time_text:
                items.append(f"{status_word} — {title} ({time_text})")
            elif status_word:
                items.append(f"{status_word} — {title}")
            else:
                items.append(f"{title}")
        else:
            items.append(f"{title}")
    return {"no_incidents": len(items) == 0, "items": items}

def format_message(components, today_info):
    lines = [
        "Aruba Central - Status",
        now_utc_str(),
        ""
    ]

    # Component status (solo no-operational)
    lines.append("Component status")
    if components:
        for name, st in components:
            lines.append(f"- {name}: {st}")
    else:
        lines.append("- All components Operational")

    # Incidents today
    lines.append("")
    lines.append("Incidents today")
    if today_info.get("no_incidents"):
        items = today_info.get("items") or []
        if items:
            for t in items:
                t = t.lstrip("• ").strip()
                lines.append(f"- {t}")
        else:
            lines.append("- No incidents reported today.")
    else:
        items = today_info.get("items") or []
        if not items:
            lines.append("- (Incidents reported today — see details on the website)")
        else:
            for t in items:
                t = t.lstrip("• ").strip()
                lines.append(f"- {t}")

    return "\n".join(lines)

# -------- NUEVO: collect() para export JSON (sin notificar) --------

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
                with open("aruba_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass

        soup = BeautifulSoup(html, "lxml")
        comps = parse_components(soup)
        today = parse_incidents_today(soup)

        # component_lines
        if comps:
            component_lines = [f"{name}: {st}" for name, st in comps]
        else:
            component_lines = ["All components Operational"]

        # incidents_lines
        if today.get("no_incidents"):
            incidents_lines = ["No incidents reported today."]
        else:
            items = today.get("items") or []
            incidents_lines = []
            for t in items:
                t = str(t).lstrip("• ").strip()
                incidents_lines.append(t if t.startswith("- ") else f"- {t}")
            if not incidents_lines:
                incidents_lines = ["- (Incidents reported today — see details on the website)"]

        overall_ok = (component_lines == ["All components Operational"] and
                      incidents_lines == ["No incidents reported today."])

        # Si conseguimos algo con sentido, devolvemos
        if component_lines or (incidents_lines and incidents_lines != ["- (Incidents reported today — see details on the website)"]):
            return {
                "name": "Aruba Central",
                "timestamp_utc": _now_utc_clean(),  # sin sufijo "UTC"
                "component_lines": component_lines,
                "incidents_lines": incidents_lines,
                "overall_ok": overall_ok,
            }

    except Exception:
        # seguimos al fallback
        pass

    # --- Fallback a Statuspage si está disponible ---
    if _HAS_STATUSPAGE:
        # Nota: build_statuspage_result añade "No incidents reported today" si aplica
        return build_statuspage_result("Aruba Central", URL.rstrip("/"))

    # Último recurso: sin datos
    return {
        "name": "Aruba Central",
        "timestamp_utc": _now_utc_clean(),
        "component_lines": [],
        "incidents_lines": ["No incidents reported today."],
        "overall_ok": None,
    }

# -------- Runner legacy (se mantiene) --------

def run():
    driver = start_driver()
    try:
        driver.get(URL)
        wait_for_page(driver)

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("aruba_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML saved to aruba_page_source.html")
            except Exception as e:
                print(f"Could not save HTML: {e}")

        soup = BeautifulSoup(html, "lxml")
        comps = parse_components(soup)
        today = parse_incidents_today(soup)

        msg = format_message(comps, today)
        print("\n===== ARUBA =====")
        print(msg)
        print("=================\n")

        # Notificaciones legacy
        send_telegram(msg)
        send_teams(msg)

    except Exception as e:
        print(f"[aruba] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"Aruba Central - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ Aruba Central - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
