# vendors/guardicore.py
import os
import re
import time
import traceback
from datetime import datetime

from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams

URL = "https://www.akamaistatus.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

DEGRADED_RE = re.compile(r"\bDegraded\b|\bDegraded Performance\b", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

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

# -------- Formato compacto como el ejemplo --------

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
            # ¿Algún hijo NO está Operational?
            any_non_oper = any(not OPERATIONAL_RE.search((c.get("status") or "")) for c in children)
            if any_non_oper:
                # Muestra el título del grupo y luego los hijos con su estado
                lines.append(f"{g['name']}")
                for c in children:
                    cname = c["name"]
                    cstatus = c.get("status") or "Unknown"
                    lines.append(f"{cname} {cstatus}")
            else:
                # Todos los hijos Operational → una sola línea
                lines.append(f"{g['name']} Operational")
        else:
            # Grupo sin hijos
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

# -------- Runner --------

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
def collect(driver):
    # Reutiliza la misma lógica que run(), pero sin notificar
    try:
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

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(driver.page_source, "lxml")
        groups = parse_component_groups(soup)
        inc = parse_incidents_today(soup)

        # Lógica compacta que ya usamos:
        component_lines = []
        for g in groups:
            children = g.get("children") or []
            if children:
                any_non_oper = any(not OPERATIONAL_RE.search((c.get("status") or "")) for c in children)
                if any_non_oper:
                    component_lines.append(f"{g['name']}")
                    for c in children:
                        cname = c["name"]
                        cstatus = c.get("status") or "Unknown"
                        component_lines.append(f"{cname} {cstatus}")
                else:
                    component_lines.append(f"{g['name']} Operational")
            else:
                status = g.get("status") or "Unknown"
                component_lines.append(f"{g['name']} {status}")

        incidents_lines = inc.get("items") or ["No incidents reported today."]
        overall_ok = all("Operational" in ln for ln in component_lines) and (
            incidents_lines == ["No incidents reported today."]
        )

        return {
            "name": "Akamai (Guardicore)",
            "component_lines": component_lines,
            "incidents_lines": incidents_lines,
            "overall_ok": overall_ok,
        }
    except Exception as e:
        return {
            "name": "Akamai (Guardicore)",
            "component_lines": [f"(error: {e})"],
            "incidents_lines": ["No incidents reported today."],
            "overall_ok": False,
        }
