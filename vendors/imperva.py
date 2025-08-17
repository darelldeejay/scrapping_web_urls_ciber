# vendors/imperva.py
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

URL = "https://status.imperva.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"
DAY_BLOCK_LIMIT = int(os.getenv("IMPERVA_DAY_LIMIT", "2"))  # nº de días a listar (por defecto 2)

# Estados problemáticos típicos de Statuspage
ISSUE_STATUS_RE = re.compile(r"(Degraded Performance|Partial Outage|Major Outage|Under Maintenance)", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

def now_utc_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    # Espera a que cargue texto relevante de componentes o incidents
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

# ---------- Componentes (solo no-operational) ----------

def parse_components(soup: BeautifulSoup):
    """
    Devuelve lista de (name, status_text) SOLO para componentes NO 'Operational'.
    Usa preferentemente data-component-status en .component-inner-container si existe.
    """
    results = []
    cards = soup.select(".components-section .component-inner-container")
    if not cards:
        # Fallback genérico: busca cualquier bloque con estado problemático
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

            # Solo si NO es operational
            if status_attr == "operational":
                continue
            if not status_attr and OPERATIONAL_RE.search(status_text):
                continue
            if not OPERATIONAL_RE.search(status_text):
                results.append((name, status_text))

    # dedup
    uniq, seen = [], set()
    for name, st in results:
        key = (name.lower(), st.lower())
        if key not in seen:
            seen.add(key)
            uniq.append((name, st))
    return uniq

# ---------- POPs afectados (heurística) ----------

POP_HINTS = re.compile(
    r"\b(POP|PoP|Point of Presence|Location\(s\)|Locations|Region\(s\)|Regions|Datacenter|Data Center|Edge|CDN)\b",
    re.I,
)

# Códigos de POP habituales (3-5 letras mayúsculas, separadas por comas/espacios)
POP_CODES = re.compile(r"\b([A-Z]{3,5})(?:\s*[,/]\s*([A-Z]{3,5}))*\b")

def extract_pops(text: str):
    """
    Extrae POPs a partir de líneas con 'POP/Locations/Regions...' o patrones de códigos mayúsculos (LHR, FRA, SJC).
    Heurística conservadora para no 'inventar' nombres.
    """
    if not text:
        return []
    cand_lines = []
    for ln in text.splitlines():
        ln = collapse_ws(ln)
        if not ln:
            continue
        if POP_HINTS.search(ln):
            cand_lines.append(ln)

    pops = set()
    for ln in cand_lines:
        # 1) Busca algo tipo 'POPs: LHR, FRA, SJC'
        m = re.search(r"(?:POP[s]?:?|Location[s]?:?|Region[s]?:?)\s*([A-Z0-9,\s/-]+)", ln, flags=re.I)
        if m:
            chunk = collapse_ws(m.group(1))
            for code in re.split(r"[,\s/;-]+", chunk):
                c = code.strip().upper()
                if re.fullmatch(r"[A-Z0-9]{3,5}", c):
                    pops.add(c)
        # 2) Extrae códigos mayúsculos aislados
        for m2 in re.finditer(r"\b[A-Z]{3,5}\b", ln):
            pops.add(m2.group(0).upper())

    # Filtra falsos positivos muy genéricos
    blacklist = {"HTTP", "HTTPS", "CDN", "DNS", "WAF", "API", "EDGE", "CACHE"}
    pops = [p for p in pops if p not in blacklist]
    # limita cantidad para que el mensaje sea legible
    pops = sorted(pops)[:12]
    return pops

# ---------- Incidents por fecha ----------

def parse_incidents_by_date(soup: BeautifulSoup, day_limit: int = 2):
    """
    Devuelve una lista de días, cada uno:
      { "date": "Aug 17, 2025", "count": N, "incidents": [ "• Resolved — Title (Aug 17, 02:40 PDT) [POPs: LHR, FRA]" ... ] }
    """
    out = []
    day_blocks = soup.select(".incidents-list .status-day")
    if not day_blocks:
        # Fallback: si el sitio solo muestra “All Systems Operational / No incidents...”
        text = collapse_ws(soup.get_text(" ", strip=True))
        if NO_INCIDENTS_TODAY_RE.search(text):
            out.append({"date": "Today", "count": 0, "incidents": ["- No incidents reported today."]})
        return out

    for day in day_blocks[:max(1, day_limit)]:
        # Fecha del bloque
        date_el = day.select_one(".date, h3, h4")
        date_str = collapse_ws(date_el.get_text(" ", strip=True)) if date_el else "Date"

        # ¿día sin incidentes?
        if "no-incidents" in (day.get("class") or []):
            msg = day.get_text(" ", strip=True)
            m = NO_INCIDENTS_TODAY_RE.search(msg)
            text = m.group(0) if m else "No incidents reported today."
            out.append({"date": date_str, "count": 0, "incidents": [f"- {text}"]})
            continue

        inc_lines = []
        for inc in day.select(".incident-container, .unresolved-incident"):
            title_el = inc.select_one(".incident-title a, .incident-title")
            title = collapse_ws(title_el.get_text(" ", strip=True)) if title_el else "Incident"
            # Última actualización (suele ser la primera card en la lista de updates)
            updates = inc.select(".updates-container .update, .incident-update")
            latest = updates[0] if updates else None
            status_word, time_text = "", ""
            if latest:
                st_el = latest.select_one("strong, .update-status, .update-title")
                tm_el = latest.select_one("small, time, .update-time")
                status_word = collapse_ws(st_el.get_text(" ", strip=True)) if st_el else ""
                time_text = collapse_ws(tm_el.get_text(" ", strip=True)) if tm_el else ""

            # POPs afectados (heurística sobre el bloque del incidente)
            raw_inc_text = collapse_ws(inc.get_text(" ", strip=True))
            pops = extract_pops(raw_inc_text)
            pop_suffix = f" [POPs: {', '.join(pops)}]" if pops else ""

            if status_word and time_text:
                inc_lines.append(f"• {status_word} — {title} ({time_text}){pop_suffix}")
            elif status_word:
                inc_lines.append(f"• {status_word} — {title}{pop_suffix}")
            else:
                inc_lines.append(f"• {title}{pop_suffix}")

        out.append({"date": date_str, "count": len(inc_lines), "incidents": inc_lines or ["- (No details)"]})

    return out

# ---------- Formato mensaje ----------

def format_message(components, days):
    lines = [
        "Imperva - Status",
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

    # Incidents by date
    lines.append("")
    lines.append("Incidents by date")
    if not days:
        lines.append("- No incidents section found.")
    else:
        for d in days:
            lines.append(f"{d['date']} — {d['count']} incident(s)")
            for line in d["incidents"]:
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
                with open("imperva_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML saved to imperva_page_source.html")
            except Exception as e:
                print(f"Could not save HTML: {e}")

        soup = BeautifulSoup(html, "lxml")
        comps = parse_components(soup)
        days = parse_incidents_by_date(soup, DAY_BLOCK_LIMIT)

        msg = format_message(comps, days)
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
