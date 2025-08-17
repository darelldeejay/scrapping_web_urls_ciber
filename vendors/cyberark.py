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
ISSUE_STATUS_RE = re.compile(r"(Degraded Performance|Partial Outage|Major Outage|Under Maintenance)", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
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
            "components" in text.lower()
            or "incidents" in text.lower()
            or ALL_OK_RE.search(text)
            or NO_INCIDENTS_TODAY_RE.search(text)
            or ISSUE_STATUS_RE.search(text)
        ):
            return
        time.sleep(0.5)

# ---------- Components (only non-operational) ----------

def parse_components(soup: BeautifulSoup):
    """
    Returns list of (name, status_text) ONLY for non-operational components.
    """
    results = []
    cards = soup.select(".components-section .component-inner-container")
    if not cards:
        # Fallback: any node with a problematic status word
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

            # Only non-operational
            if status_attr == "operational":
                continue
            if not status_attr and OPERATIONAL_RE.search(status_text):
                continue
            if OPERATIONAL_RE.search(status_text):
                continue

            results.append((name, status_text))

    # Dedup
    uniq, seen = [], set()
    for name, st in results:
        key = (name.lower(), st.lower())
        if key not in seen:
            seen.add(key)
            uniq.append((name, st))
    return uniq

# ---------- Incidents: ONLY today's block ----------

def today_header_strings():
    now = datetime.utcnow()
    with_zero = now.strftime("%b %d, %Y")   # "Aug 07, 2025"
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
    # Fallback: a block marked as 'today'
    for day in day_blocks:
        if "today" in (day.get("class") or []):
            date_el = day.select_one(".date, h3, h4")
            date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else "Today"
            return day, date_str
    return None, None

def parse_incidents_today(soup: BeautifulSoup):
    """
    Returns dict:
      { "date": "Aug 17, 2025", "count": N, "items": [ "• Resolved — Title (Aug 17, 02:40 PDT)" ... ] }
    If 'No incidents reported today.' appears, returns that.
    """
    day, date_str = find_today_day_block(soup)
    if not day:
        full = collapse_ws(soup.get_text(" ", strip=True))
        if NO_INCIDENTS_TODAY_RE.search(full):
            return {"date": list(today_header_strings())[0], "count": 0, "items": ["- No incidents reported today."]}
        return {"date": list(today_header_strings())[0], "count": 0, "items": ["- No incidents section found."]}

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

# ---------- Message ----------

def format_message(non_operational_components, today_inc, banner_text=None):
    lines = [
        "CyberArk Privilege Cloud - Status",
        now_utc_str(),
        ""
    ]

    # System status
    if non_operational_components:
        lines.append("System status: Issues detected")
    else:
        # Prefer banner text if available and matches "All Systems Operational"
        if banner_text and ALL_OK_RE.search(banner_text):
            lines.append("System status: All Systems Operational")
        else:
            lines.append("System status: All Systems Operational")

    # Components
    lines.append("")
    lines.append("Component status")
    if non_operational_components:
        for name, st in non_operational_components:
            lines.append(f"- {name}: {st}")
    else:
        lines.append("- All components Operational")

    # Incidents today
    lines.append("")
    lines.append("Incidents today")
    lines.append(f"{today_inc.get('date', 'Today')} — {today_inc.get('count', 0)} incident(s)")
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

        # Banner (optional)
        banner_text = None
        banner = soup.select_one(".page-status .status, .status-description, .page-status")
        if banner:
            banner_text = collapse_ws(banner.get_text(" ", strip=True))

        non_operational = parse_components(soup)
        today_inc = parse_incidents_today(soup)

        msg = format_message(non_operational, today_inc, banner_text)
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
