# vendors/netskope.py
# -*- coding: utf-8 -*-
"""
Netskope — soporte dual:
- run(): ejecución clásica con Selenium + notificación (Telegram/Teams)
- collect(driver): reutiliza el parseo para export JSON (sin notificar)
  con formato normalizado para el digest.

Reglas aplicadas:
- Secciones: "Open Incidents" y "Past Incidents (Previous 15 days)".
- Evitar falsos activos si el último estado es "Resolved".
- Inicio = primer 'Investigating'/'Identified'; Fin = 'Resolved' (si existe).
- Fechas normalizadas a UTC.
"""

import os
import re
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional

from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams

# =========================
# Configuración
# =========================
NETSKOPE_URL = "https://trustportal.netskope.com/incidents"
LOOKBACK_DAYS = 15
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# =========================
# Helpers de fechas/parseo
# =========================
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic"
DATE_REGEX_LOOSE = rf"({MONTHS})\s+\d{{1,2}}(?:,\s*\d{{4}})?(?:\s*,?\s*\d{{1,2}}:\d{{2}}\s*(?:AM|PM)?(?:\s*(?:UTC|GMT|[A-Z]{{2,4}}))?)?"
STATUS_TOKENS = ["Resolved", "Mitigated", "Monitoring", "Identified", "Investigating", "Degraded", "Update"]

def now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _now_utc_clean() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def parse_datetime_any(text: str) -> Optional[datetime]:
    try:
        dt = dateparser.parse(text, fuzzy=True)
        if dt:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    m = re.search(DATE_REGEX_LOOSE, text or "", flags=re.I)
    if m:
        try:
            dt = dateparser.parse(m.group(0), fuzzy=True)
            if dt:
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None

def dt_fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "-"

def nearest_date_after(label_text: str, full_text: str) -> Optional[datetime]:
    try:
        pos = (full_text or "").lower().find(label_text.lower())
        if pos == -1:
            return None
        window = full_text[pos: pos + 500]
        m = re.search(DATE_REGEX_LOOSE, window, flags=re.I)
        if m:
            return parse_datetime_any(m.group(0))
    except Exception:
        pass
    return None

def nearest_date_after_any(labels: List[str], text: str) -> Optional[datetime]:
    for lab in labels:
        dt = nearest_date_after(lab, text)
        if dt:
            return dt
    return None

def latest_status_from_text(text: str) -> Optional[str]:
    low = (text or "").lower()
    # El "último" evento en el portal suele estar al principio del bloque
    candidates = ["resolved", "mitigated", "monitoring", "identified", "investigating", "degraded", "update"]
    for tok in candidates:
        if tok in low:
            return tok.title()
    return None

def find_nearest_header_date(node) -> Optional[datetime]:
    cur = node; steps = 0
    while cur and steps < 15:
        sib = getattr(cur, "previous_sibling", None)
        while sib:
            if getattr(sib, "get_text", None):
                txt = sib.get_text(strip=True)
                dt = parse_datetime_any(txt)
                if dt:
                    return dt
            sib = getattr(sib, "previous_sibling", None)
        cur = getattr(cur, "parent", None); steps += 1
    return None

def incident_container_for(node):
    cur = node
    for _ in range(8):
        if not hasattr(cur, "get_text"):
            break
        classes = cur.get("class") if hasattr(cur, "get") else None
        class_str = " ".join(classes).lower() if isinstance(classes, list) else (classes or "")
        txt = cur.get_text(" ", strip=True).lower()
        if ("incident" in class_str) or any(s in txt for s in [
            "resolved", "mitigated", "investigating", "identified", "update", "monitoring", "degraded"
        ]):
            return cur
        cur = getattr(cur, "parent", None)
        if cur is None:
            break
    return node

def wait_for_page(driver):
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(., 'Incidents') or contains(., 'Open Incidents') or contains(., 'Past Incidents')]")
        )
    )

# =========================
# Localización de secciones y tarjetas
# =========================
def extract_sections_strict(soup: BeautifulSoup) -> Tuple[List, List]:
    def find_heading(keywords: List[str]):
        for kw in keywords:
            h = soup.find(
                lambda tag: tag.name in ["h1","h2","h3","h4","div","summary"]
                and tag.get_text(strip=True)
                and kw.lower() in tag.get_text(strip=True).lower()
            )
            if h: return h
        return None

    def collect_after(heading, stop_keywords: List[str]):
        cards = []
        if not heading:
            return cards
        for node in heading.find_all_next(True):
            if node.name in ["h1","h2","h3","h4","summary"]:
                txt = node.get_text(strip=True).lower()
                if any(sk in txt for sk in stop_keywords):
                    break
            cards.extend(node.select(".incident, [class*='incident'], a[href*='/incidents/']"))
        return cards

    open_heading = find_heading(["Open Incidents", "Active Incidents", "Active", "Current incidents"])
    past_heading = find_heading(["Past Incidents (Previous 15 days)", "Past Incidents", "Previous 15 days"])

    open_cards = collect_after(open_heading, ["past incidents", "previous 15 days", "maintenance", "status", "home"])
    past_cards = collect_after(past_heading, ["open incidents", "maintenance", "status", "home"])

    if not past_cards:
        all_anchors = soup.select("a[href*='/incidents/']")
        open_hrefs = set()
        for c in open_cards:
            a = c if c.name == "a" else c.find("a", href=True)
            if a and "/incidents" in a.get("href", ""):
                open_hrefs.add(a["href"])
        past_cards = [a for a in all_anchors if a.get("href") not in open_hrefs]

    return open_cards, past_cards

def normalize_card(card) -> dict:
    container = card
    if getattr(card, "name", None) == "a":
        container = incident_container_for(card)

    # URL + título
    incident_link = None
    for a in container.find_all("a", href=True):
        href = a.get("href", "")
        if "/incidents" in href:
            txt = a.get_text(" ", strip=True)
            if re.search(r"\bIncident\s+\d+", txt, flags=re.I):
                incident_link = a; break
            if not incident_link:
                incident_link = a
    if incident_link:
        href = incident_link["href"]
        url = "https://trustportal.netskope.com" + href if href.startswith("/") else href
        title = incident_link.get_text(" ", strip=True)
    else:
        url = None
        title = None
        el = container.find(class_=re.compile(r"incident-title|card-title", re.I))
        if el: title = el.get_text(strip=True)
        if not title:
            h = container.find(["h1","h2","h3","h4"])
            if h: title = h.get_text(strip=True)
        if not title:
            title = "Netskope Incident"

    text = container.get_text(" ", strip=True) if hasattr(container, "get_text") else ""

    # Fechas
    started_at = None
    ended_at = None

    times = container.find_all("time") if hasattr(container, "find_all") else []
    parsed_times = []
    for t in times:
        dt = parse_datetime_any(t.get("datetime") or t.get_text(strip=True))
        if dt: parsed_times.append(dt)
    if parsed_times:
        parsed_times.sort()
        started_at = parsed_times[0]
        ended_at = parsed_times[-1]

    # Regex global (por si no hay <time>)
    all_dates = [parse_datetime_any(m.group(0)) for m in re.finditer(DATE_REGEX_LOOSE, text or "", flags=re.I)]
    all_dates = [d for d in all_dates if d]

    # Inicio
    start_from_label = nearest_date_after_any(["Investigating", "Identified"], text)
    if start_from_label:
        started_at = start_from_label
    elif not started_at and all_dates:
        started_at = min(all_dates)

    # Fin (solo Resolved)
    end_from_resolved = nearest_date_after("Resolved", text)
    if end_from_resolved:
        ended_at = end_from_resolved
    elif not ended_at and all_dates:
        ended_at = max(all_dates)

    if not started_at:
        started_at = find_nearest_header_date(container)

    status = latest_status_from_text(text) or "Update"

    return {
        "title": title,
        "status": status,
        "url": url,
        "started_at": started_at,
        "ended_at": ended_at,
        "raw_text": text,
    }

def dedup_incidents(items: List[dict]) -> List[dict]:
    seen = set(); out = []
    for it in items:
        key = ((it.get("title") or "").strip(), (it.get("url") or "").strip())
        if key in seen: continue
        seen.add(key); out.append(it)
    return out

# =========================
# Scrape + clasificación
# =========================
def analizar_netskope(driver) -> Tuple[List[dict], List[dict]]:
    print("🔍 Cargando Netskope…")
    driver.get(NETSKOPE_URL)
    wait_for_page(driver)

    # Intentar expandir "Past Incidents" si es colapsable
    try:
        candidatos = [
            "Past Incidents (Previous 15 days)",
            "Past Incidents",
            "Previous 15 days",
        ]
        for label in candidatos:
            elems = driver.find_elements(By.XPATH, f"//*[contains(normalize-space(.), '{label}')]")
            for el in elems:
                tag = (el.tag_name or "").lower()
                txt = (el.text or "").strip()
                if not txt:
                    continue
                if tag in ("summary", "button"):
                    try:
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                        el.click()
                        time.sleep(1)
                        raise StopIteration
                    except Exception:
                        pass
    except StopIteration:
        pass
    except Exception:
        pass

    # Espera a que aparezca al menos un enlace de incidente
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/incidents/']"))
        )
    except Exception:
        pass

    time.sleep(1.5)

    html = driver.page_source
    if SAVE_HTML:
        try:
            with open("netskope_page_source.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("💾 HTML guardado en netskope_page_source.html")
        except Exception as e:
            print(f"No se pudo guardar HTML: {e}")

    soup = BeautifulSoup(html, "lxml")
    open_cards, past_cards = extract_sections_strict(soup)

    activos = [normalize_card(c) for c in open_cards]
    pasados = [normalize_card(c) for c in past_cards]
    activos = dedup_incidents(activos)
    pasados = dedup_incidents(pasados)

    # Quitar de 'activos' cualquier incidente presente en 'pasados'
    past_urls = {i.get("url") for i in pasados if i.get("url")}
    past_titles = {(i.get("title") or "").strip() for i in pasados}
    activos = [
        i for i in activos
        if (i.get("url") not in past_urls) and ((i.get("title") or "").strip() not in past_titles)
    ]

    # Filtrar 'pasados' a 15 días
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)

    def in_lookback(inc):
        dt = inc.get("ended_at") or inc.get("started_at")
        if not dt:
            return True  # normalmente ya están en la sección "Previous 15 days"
        return dt >= cutoff

    pasados_15 = [i for i in pasados if in_lookback(i)]

    # En activos, descartar cualquier 'Resolved'
    activos = [i for i in activos if (i.get("status") or "").lower() != "resolved"]

    return activos, pasados_15

# =========================
# Formato de salida (texto limpio)
# =========================
def format_incidente_line(it: dict, idx: Optional[int] = None, resolved_section: bool = False) -> List[str]:
    """
    Devuelve líneas para un incidente:
    - Línea principal: "N. <Status> — <Title> (<URL>)"
    - Línea de fechas:
        * resolved_section=True -> "   Inicio: ... · Fin: ..."
        * resolved_section=False -> "   Inicio: ... · Últ. act.: ..."
    """
    title = collapse_ws(it.get("title") or "Incident")
    status = (it.get("status") or "Update").title()
    url = it.get("url") or ""
    started = it.get("started_at")
    ended = it.get("ended_at")

    num = f"{idx}. " if idx is not None else ""
    main = f"{num}{status} — {title}"
    if url:
        main += f" ({url})"

    if resolved_section:
        date_line = f"   Inicio: {dt_fmt(started)} · Fin: {dt_fmt(ended)}"
    else:
        date_line = f"   Inicio: {dt_fmt(started)} · Últ. act.: {dt_fmt(ended)}"

    return [main, date_line]

def format_message(activos: List[dict], pasados_15: List[dict]) -> str:
    lines = [
        "Netskope - Estado de Incidentes",
        now_utc_str(),
        ""
    ]
    # Activos
    lines.append("Incidentes activos")
    if not activos:
        lines.append("- No hay incidentes activos reportados.")
    else:
        for i, it in enumerate(activos, 1):
            lines.extend(format_incidente_line(it, idx=i, resolved_section=False))

    # Pasados (15 días resueltos)
    lines.append("")
    lines.append("Últimos 15 días (resueltos)")
    if not pasados_15:
        lines.append("- No hay incidentes en los últimos 15 días.")
    else:
        for i, it in enumerate(pasados_15, 1):
            lines.extend(format_incidente_line(it, idx=i, resolved_section=True))

    return "\n".join(lines)

# =========================
# Export normalizado para digest (sin notificar)
# =========================
def collect(driver):
    """
    Reutiliza el scraping y devuelve dict normalizado para el digest:
      {
        "name": "Netskope",
        "timestamp_utc": "YYYY-MM-DD HH:MM",
        "component_lines": [],
        "incidents_lines": [ "Incidentes activos", "- ...", "", "Últimos 15 días (resueltos)", "1. ..." ],
        "overall_ok": bool
      }
    """
    activos, pasados_15 = analizar_netskope(driver)

    # component_lines vacío (Netskope no expone componentes)
    component_lines: List[str] = []

    # incidents_lines estructurado
    incidents_lines: List[str] = []
    incidents_lines.append("Incidentes activos")
    if not activos:
        incidents_lines.append("- No hay incidentes activos reportados.")
    else:
        for i, it in enumerate(activos, 1):
            incidents_lines.extend(format_incidente_line(it, idx=i, resolved_section=False))
    incidents_lines.append("")
    incidents_lines.append("Últimos 15 días (resueltos)")
    if not pasados_15:
        incidents_lines.append("- No hay incidentes en los últimos 15 días.")
    else:
        for i, it in enumerate(pasados_15, 1):
            incidents_lines.extend(format_incidente_line(it, idx=i, resolved_section=True))

    overall_ok = (not activos)

    return {
        "name": "Netskope",
        "timestamp_utc": _now_utc_clean(),
        "component_lines": component_lines,
        "incidents_lines": incidents_lines,
        "overall_ok": overall_ok,
    }

# =========================
# Entrypoint del vendor (con notificaciones)
# =========================
def run():
    driver = start_driver()
    try:
        activos, pasados_15 = analizar_netskope(driver)
        resumen = format_message(activos, pasados_15)

        print("\n===== NETSKOPE =====")
        print(resumen)
        print("====================\n")

        send_telegram(resumen)
        send_teams(resumen)
    except Exception as e:
        print(f"[netskope] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"Netskope - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ Netskope - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
