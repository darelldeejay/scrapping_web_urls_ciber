# vendors/trendmicro.py
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

SITES = [
    {
        "name": "Trend Cloud One",
        "slug": "trend-cloud-one",
        "url": "https://status.trendmicro.com/en-US/trend-cloud-one/",
    },
    {
        "name": "Trend Vision One",
        "slug": "trend-vision-one",
        "url": "https://status.trendmicro.com/en-US/trend-vision-one/",
    },
]

SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def today_header_strings():
    now = datetime.utcnow()
    with_zero = now.strftime("%b %d, %Y")   # "Aug 07, 2025"
    no_zero  = with_zero.replace(" 0", " ") # "Aug 7, 2025"
    return {with_zero, no_zero}

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    # Espera a que aparezca la sección de incidentes o el mensaje de no-incidentes
    for _ in range(40):
        body = driver.find_element(By.TAG_NAME, "body").text
        text = collapse_ws(body)
        if "past incidents" in text.lower() or NO_INCIDENTS_TODAY_RE.search(text):
            return
        time.sleep(0.5)

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
    # Fallback: bloque marcado como 'today'
    for day in day_blocks:
        if "today" in (day.get("class") or []):
            date_el = day.select_one(".date, h3, h4")
            date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else "Today"
            return day, date_str
    return None, None

def parse_incidents_today(soup: BeautifulSoup):
    """
    Devuelve dict:
      { "count": N, "items": [ "• Resolved — Title (Aug 17, 02:40 ...)" ... ] }
    Solo cuenta el día actual. Si no hay, devuelve count=0 y items=[].
    """
    day, _date_str = find_today_day_block(soup)
    if not day:
        # Fallback: mirar si el global dice "No incidents reported today"
        full = collapse_ws(soup.get_text(" ", strip=True))
        if NO_INCIDENTS_TODAY_RE.search(full):
            return {"count": 0, "items": []}
        # Si no encontramos nada, devolvemos vacío (no notificamos)
        return {"count": 0, "items": []}

    if "no-incidents" in (day.get("class") or []):
        # Día explícitamente sin incidentes
        return {"count": 0, "items": []}

    items = []
    for inc in day.select(".incident-container, .unresolved-incident"):
        title_el = inc.select_one(".incident-title a, .incident-title")
        title = collapse_ws(title_el.get_text(" ", strip=True)) if title_el else "Incident"

        # Última actualización (normalmente la primera tarjeta en la lista de updates)
        updates = inc.select(".updates-container .update, .incident-update")
        latest = updates[0] if updates else None
        status_word, time_text = "", ""
        if latest:
            st_el = latest.select_one("strong, .update-status, .update-title")
            tm_el = latest.select_one("small, time, .update-time")
            status_word = collapse_ws(st_el.get_text(" ", strip=True)) if st_el else ""
            time_text = collapse_ws(tm_el.get_text(" ", strip=True)) if tm_el else ""
        # Formato final
        if status_word and time_text:
            items.append(f"• {status_word} — {title} ({time_text})")
        elif status_word:
            items.append(f"• {status_word} — {title}")
        else:
            items.append(f"• {title}")

    return {"count": len(items), "items": items}

def run():
    driver = start_driver()
    try:
        any_incidents = False
        sections = []

        for site in SITES:
            name = site["name"]
            url = site["url"]
            slug = site["slug"]

            driver.get(url)
            wait_for_page(driver)

            html = driver.page_source
            if SAVE_HTML:
                try:
                    fname = f"trend_{slug}_page_source.html"
                    with open(fname, "w", encoding="utf-8") as f:
                        f.write(html)
                    print(f"💾 HTML saved to {fname}")
                except Exception as e:
                    print(f"Could not save HTML for {name}: {e}")

            soup = BeautifulSoup(html, "lxml")
            today = parse_incidents_today(soup)

            # Solo añadimos sección si hay incidentes hoy
            if today["count"] > 0:
                any_incidents = True
                lines = [f"[{name}]"]
                if today["count"] > 0:
                    lines.append(f"Incidents today — {today['count']} incident(s)")
                for line in today["items"]:
                    lines.append(line)
                sections.append("\n".join(lines))

        # Solo notificar si hay al menos un incidente hoy en alguna de las dos consolas
        if any_incidents:
            msg_lines = [
                "Trend Micro - Status",
                now_utc_str(),
                ""
            ]
            msg_lines.append("\n\n".join(sections))
            msg = "\n".join(msg_lines)
            print("\n===== TREND MICRO =====")
            print(msg)
            print("=======================\n")
            send_telegram(msg)
            send_teams(msg)
        else:
            # Nada que notificar hoy
            print("Trend Micro: no incidents today in Cloud One or Vision One. No notification sent.")

    except Exception as e:
        print(f"[trendmicro] ERROR: {e}")
        traceback.print_exc()
        # Notifica el error para que sepas que el job falló
        send_telegram(f"Trend Micro - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ Trend Micro - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
