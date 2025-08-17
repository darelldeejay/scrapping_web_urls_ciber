# vendors/guardicore.py
import os
import re
import time
import traceback
from datetime import datetime

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams

URL = "https://www.akamaistatus.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# Patrones/estados típicos
DEGRADED_RE = re.compile(r"\bDegraded\b|\bDegraded Performance\b", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    # Espera a que cargue algo propio de la página (checks/incidents)
    for _ in range(60):
        body = driver.find_element(By.TAG_NAME, "body").text
        text = collapse_ws(body)
        if ("past incidents" in text.lower()
            or "components" in text.lower()
            or "services" in text.lower()
            or NO_INCIDENTS_TODAY_RE.search(text)
            or OPERATIONAL_RE.search(text)
            or DEGRADED_RE.search(text)):
            return
        time.sleep(0.3)

# ---------- CHECKS: solo 'Operational' o 'Degraded' ----------

def parse_checks(soup: BeautifulSoup):
    """
    Devuelve lista de dicts:
      { "name": "X", "status": "Operational|Degraded Performance|Degraded" }
    Solo incluye los que sean 'Operational' o 'Degraded*'.
    """
    results = []

    # Intento 1: estructura tipo Statuspage
    cards = soup.select(
        ".components-section .component-inner-container, "
        ".component-inner-container, "
        ".component-container, "
        ".component"
    )

    def grab_name(comp):
        el = comp.select_one(".name, .component-name, [data-component-name]")
        if el:
            return collapse_ws(el.get_text(" ", strip=True))
        if comp.has_attr("data-component-name"):
            return collapse_ws(comp["data-component-name"])
        # Fallback: primer texto “grande”
        txt = collapse_ws(comp.get_text(" ", strip=True))
        # recorta si aparece la palabra 'Operational' o 'Degraded'
        m = re.search(r"(Operational|Degraded Performance|Degraded)", txt, flags=re.I)
        if m:
            pos = txt.lower().find(m.group(1).lower())
            return collapse_ws(txt[:pos])
        return txt[:80] or "Component"

    def grab_status(comp):
        # Atributo
        status_attr = (comp.get("data-component-status") or "").strip()
        if status_attr:
            return status_attr
        # Nodo de estado
        el = comp.select_one(".component-status, .status, .component-status-container")
        if el:
            return collapse_ws(el.get_text(" ", strip=True))
        # Fallback textual
        txt = collapse_ws(comp.get_text(" ", strip=True))
        m = re.search(r"(Degraded Performance|Degraded|Operational)", txt, flags=re.I)
        return m.group(1) if m else ""

    for comp in cards:
        name = grab_name(comp)
        st = grab_status(comp)
        st_norm = st.strip()
        if not st_norm:
            continue
        if OPERATIONAL_RE.search(st_norm) or DEGRADED_RE.search(st_norm):
            results.append({"name": name, "status": st_norm})

    # Intento 2 (si no hubo tarjetas): escaneo genérico de bloques con “Operational/Degraded”
    if not results:
        for tag in soup.find_all(True):
            txt = collapse_ws(getattr(tag, "get_text", lambda *a, **k: "")(" ", strip=True))
            m = re.search(r"(.*?)(?:\s*[:\-–]\s*)?(Degraded Performance|Degraded|Operational)\b", txt, flags=re.I)
            if m:
                name = collapse_ws(m.group(1)) or "Component"
                st = m.group(2)
                # Evita capturar líneas de "No incidents reported today" o cabeceras
                if "incident" in name.lower() or "past incidents" in name.lower():
                    continue
                if OPERATIONAL_RE.search(st) or DEGRADED_RE.search(st):
                    results.append({"name": name, "status": st})

    # Dedup y ordena con Degraded primero
    uniq, seen = [], set()
    for item in results:
        key = (item["name"].lower(), item["status"].lower())
        if key not in seen:
            seen.add(key)
            uniq.append(item)
    uniq.sort(key=lambda x: (0 if DEGRADED_RE.search(x["status"]) else 1, x["name"].lower()))
    return uniq

# ---------- INCIDENTS: SOLO hoy en 'Past Incidents' ----------

def today_header_strings():
    now = datetime.utcnow()
    with_zero = now.strftime("%b %d, %Y")   # "Aug 17, 2025"
    no_zero  = with_zero.replace(" 0", " ") # "Aug 7, 2025"
    return {with_zero, no_zero}

def find_today_block(soup: BeautifulSoup):
    # Bloques típicos de Statuspage
    day_blocks = soup.select(".incidents-list .status-day, .status-day")
    if not day_blocks:
        return None, None
    candidates = today_header_strings()
    for day in day_blocks:
        date_el = day.select_one(".date, h3, h4")
        date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else ""
        if date_str in candidates:
            return day, date_str
    # Fallback: clase 'today'
    for day in day_blocks:
        if "today" in (day.get("class") or []):
            date_el = day.select_one(".date, h3, h4")
            date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else "Today"
            return day, date_str
    return None, None

def parse_incidents_today(soup: BeautifulSoup):
    """
    Devuelve dict:
      {"date": "...", "count": N, "items": ["• Resolved — Title (HH:MM TZ)", ...]}
    Si no hay bloque de hoy, intenta detectar el literal "No incidents reported today." global y lo reporta.
    """
    day, date_str = find_today_block(soup)
    default_date = list(today_header_strings())[0]

    if not day:
        full = collapse_ws(soup.get_text(" ", strip=True))
        if NO_INCIDENTS_TODAY_RE.search(full):
            return {"date": default_date, "count": 0, "items": ["- No incidents reported today."]}
        return {"date": default_date, "count": 0, "items": ["- No incidents section found."]}

    # Día sin incidentes explícito
    if "no-incidents" in (day.get("class") or []):
        msg = day.get_text(" ", strip=True)
        m = NO_INCIDENTS_TODAY_RE.search(msg)
        text = m.group(0) if m else "No incidents reported today."
        return {"date": date_str, "count": 0, "items": [f"- {text}"]}

    lines = []
    # Incidentes (estructura típica de Statuspage)
    for inc in day.select(".incident-container, .unresolved-incident, .incident"):
        title_el = inc.select_one(".incident-title a, .incident-title")
        title = collapse_ws(title_el.get_text(" ", strip=True)) if title_el else "Incident"

        # Última actualización (primera card en updates)
        updates = inc.select(".updates-container .update, .incident-update, .update")
        latest = updates[0] if updates else None
        status_word, time_text = "", ""
        if latest:
            st_el = latest.select_one("strong, .update-status, .update-title")
            tm_el = latest.select_one("small, time, .update-time")
            status_word = collapse_ws(st_el.get_text(" ", strip=True)) if st_el else ""
            time_text = collapse_ws(tm_el.get_text(" ", strip=True)) if tm_el else ""

        if status_word and time_text:
            lines.append(f"• {status_word} — {title} ({time_text})")
        elif status_word:
            lines.append(f"• {status_word} — {title}")
        else:
            lines.append(f"• {title}")

    return {"date": date_str, "count": len(lines), "items": lines or ["- (No details)"]}

# ---------- Formato mensaje ----------

def format_message(checks, today_inc):
    lines = [
        "Akamai (Guardicore) - Status",
        now_utc_str(),
        ""
    ]

    # Checks
    lines.append("Checks")
    if checks:
        # Si todos están Operational, confírmalo y muestra el total.
        if all(OPERATIONAL_RE.search(c["status"]) for c in checks):
            lines.append("- All checks Operational")
        else:
            for c in checks:
                lines.append(f"- {c['name']}: {c['status']}")
    else:
        # Si no detectamos estructura de checks, al menos no inventar nada
        lines.append("- (No checks found)")

    # Incidents today (sin repetir la fecha ni “— 0 incident(s)”)
    lines.append("")
    lines.append("Incidents today")
    if today_inc.get("count", 0) > 0:
        for line in today_inc["items"]:
            lines.append(line)
    else:
        # Si vino el literal, úsalo; si no, fallback
        items = today_inc.get("items") or []
        if items:
            for it in items:
                lines.append(it)
        else:
            lines.append("- No incidents reported today.")

    return "\n".join(lines)

# ---------- Runner ----------

def run():
    driver = start_driver()
    try:
        driver.get(URL)
        wait_for_page(driver)

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("akamai_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML saved to akamai_page_source.html")
            except Exception as e:
                print(f"Could not save HTML: {e}")

        soup = BeautifulSoup(html, "lxml")
        checks = parse_checks(soup)
        today_inc = parse_incidents_today(soup)

        msg = format_message(checks, today_inc)
        print("\n===== AKAMAI (GUARDICORE) =====")
        print(msg)
        print("================================\n")

        send_telegram(msg)
        send_teams(msg)

    except Exception as e:
        print(f"[guardicore] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"Akamai (Guardicore) - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ Akamai (Guardicore) - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
