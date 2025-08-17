# vendors/aruba.py
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

URL = "https://centralstatus.arubanetworking.hpe.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# Regex helpers
ISSUE_STATUS_RE = re.compile(r"(Degraded Performance|Partial Outage|Major Outage|Under Maintenance)", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    # Espera a que aparezca sección de componentes o texto de incidentes
    for _ in range(40):
        body = driver.find_element(By.TAG_NAME, "body").text
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
    Devuelve una lista de (name, status_text) SOLO para componentes NO 'Operational'.
    Intenta usar data-component-status='operational' si está presente.
    """
    results = []
    cards = soup.select(".components-section .component-inner-container")
    if not cards:
        # Fallback genérico: cualquier bloque con un estado problemático
        for tag in soup.find_all(True):
            txt = collapse_ws(getattr(tag, "get_text", lambda *a, **k: "")(" ", strip=True))
            m = ISSUE_STATUS_RE.search(txt)
            if m:
                # intenta extraer un nombre aproximado anterior al estado
                pos = txt.lower().find(m.group(1).lower())
                name = collapse_ws(txt[:pos]) if pos > 0 else "Component"
                results.append((name, m.group(1)))
        # dedup
        uniq = []
        seen = set()
        for name, st in results:
            key = (name.lower(), st.lower())
            if key not in seen:
                seen.add(key)
                uniq.append((name, st))
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
        # Solo reportar si NO es operational
        if status_attr and status_attr == "operational":
            continue
        if not status_attr and OPERATIONAL_RE.search(status_text):
            continue
        if not OPERATIONAL_RE.search(status_text):
            results.append((name, status_text))
    # dedup
    uniq = []
    seen = set()
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
    # Primer bloque del histórico (día más reciente)
    day_block = soup.select_one(".incidents-list .status-day")
    if not day_block:
        # Fallback por texto
        full_text = collapse_ws(soup.get_text(" ", strip=True))
        if NO_INCIDENTS_TODAY_RE.search(full_text):
            return {"no_incidents": True, "items": []}
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
            status_word = collapse_ws(latest.select_one("strong").get_text(" ", strip=True)) if latest.select_one("strong") else ""
            time_text = collapse_ws(latest.select_one("small").get_text(" ", strip=True)) if latest.select_one("small") else ""
            if status_word and time_text:
                items.append(f"• {status_word} — {title} ({time_text})")
            elif status_word:
                items.append(f"• {status_word} — {title}")
            else:
                items.append(f"• {title}")
        else:
            items.append(f"• {title}")
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
        # Si vino texto literal de la página, úsalo; si no, frase por defecto (en inglés)
        items = today_info.get("items") or []
        if items:
            for t in items:
                lines.append(f"- {t}")
        else:
            lines.append("- No incidents reported today.")
    else:
        items = today_info.get("items") or []
        if not items:
            lines.append("- (Incidents reported today — see details on the website)")
        else:
            lines.extend(items)

    return "\n".join(lines)

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
