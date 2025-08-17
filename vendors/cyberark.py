# vendors/cyberark.py
import os
import re
import time
from datetime import datetime

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams

URL = "https://privilegecloud-service-status.cyberark.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# Statuspage-like patterns
ALL_OK_RE = re.compile(r"All Systems Operational", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    for _ in range(40):
        body = driver.find_element(By.TAG_NAME, "body").text
        text = collapse_ws(body)
        if (
            "past incidents" in text.lower()
            or ALL_OK_RE.search(text)
            or NO_INCIDENTS_TODAY_RE.search(text)
        ):
            return
        time.sleep(0.5)

# ---------- Incidents: ONLY today's block ----------

def today_header_strings():
    now = datetime.utcnow()
    with_zero = now.strftime("%b %d, %Y")   # "Aug 17, 2025"
    no_zero  = with_zero.replace(" 0", " ") # "Aug 7, 2025"
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
      { "date": "Aug 17, 2025", "count": N, "items": [ "• Resolved — Title (Aug 17, 02:40 UTC)" ... ] }
    Si aparece 'No incidents reported today.', lo reporta tal cual.
    """
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
        if status_word and time_text:
            items.append(f"• {status_word} — {title} ({time_text})")
        elif status_word:
            items.append(f"• {status_word} — {title}")
        else:
            items.append(f"• {title}")

    return {"date": date_str, "count": len(items), "items": items or ["- (No details)"]}

# ---------- Message (no date duplication; hide "— 0 incident(s)") ----------

def format_message(system_status_text, today_inc):
    lines = [
        "CyberArk Privilege Cloud - Status",
        now_utc_str(),
        ""
    ]

    # System status (banner)
    if system_status_text:
        lines.append(f"System status: {system_status_text}")
    else:
        lines.append("System status: (unknown)")

    # Incidents today: if zero, don't show "— 0 incident(s)"
    lines.append("")
    if today_inc.get("count", 0) > 0:
        lines.append(f"Incidents today — {today_inc['count']} incident(s)")
    else:
        lines.append("Incidents today")
    for line in (today_inc.get("items") or ["- No incidents reported today."]):
        lines.append(line)

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
                with open("cyberark_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML saved to cyberark_page_source.html")
            except Exception as e:
                print(f"Could not save HTML: {e}")

        soup = BeautifulSoup(html, "lxml")

        # Banner: <div class="page-status ..."><h2 class="status ...">All Systems Operational</h2>...</div>
        system_status_text = None
        banner = soup.select_one(".page-status .status")
        if banner:
            system_status_text = collapse_ws(banner.get_text(" ", strip=True))

        today_inc = parse_incidents_today(soup)

        msg = format_message(system_status_text, today_inc)
        print("\n===== CYBERARK =====")
        print(msg)
        print("====================\n")

        send_telegram(msg)
        send_teams(msg)

    except Exception as e:
        print(f"[cyberark] ERROR: {e}")
        send_telegram(f"CyberArk Privilege Cloud - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ CyberArk Privilege Cloud - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
