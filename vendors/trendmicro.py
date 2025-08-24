# vendors/trendmicro.py
# -*- coding: utf-8 -*-
"""
Trend Micro — soporte dual:
- run(): ejecución con Selenium + notificación combinada (Telegram/Teams)
- collect(driver): export JSON normalizado para el digest

Reglas:
- Se leen los arrays `sspDataInfo` embebidos en <script>.
- Se filtra por producto (Cloud One / Vision One).
- Se agrupa por incidente y se toma la última actualización de HOY (UTC).
- Mensajes en texto plano (sin HTML).
- Si no hay incidentes de hoy, se muestra el literal de la página “No incidents reported today.”
"""

import os
import re
import time
import html as htmlmod
import json
import traceback
from datetime import datetime, timezone
from urllib.parse import unquote
from typing import List, Dict, Any, Tuple, Optional

from bs4 import BeautifulSoup
from dateutil import parser as dtparser
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
        "product": "Trend Cloud One",
    },
    {
        "name": "Trend Vision One",
        "slug": "trend-vision-one",
        "url": "https://status.trendmicro.com/en-US/trend-vision-one/",
        "product": "Trend Vision One",
    },
]

SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

STATUS_MAP = {
    770060000: "Resolved",
    770060001: "Monitoring",
    770060002: "Investigating",
    770060003: "Identified",
    770060004: "Update",
    770060005: "Mitigated",
}

# ---------------- Utilidades ---------------- #

def now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _now_utc_clean() -> str:
    """Para export JSON (sin sufijo 'UTC'; lo añade el renderer)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver) -> None:
    """
    Considera la página lista cuando hay body y:
    - aparece 'past incidents' o el literal de no-incidentes, o
    - encontramos 'sspDataInfo' en el HTML (la fuente real de datos).
    """
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    for _ in range(60):
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            body = ""
        text = collapse_ws(body)
        if ("past incidents" in text.lower()) or NO_INCIDENTS_TODAY_RE.search(text) or ("sspDataInfo" in driver.page_source):
            return
        time.sleep(0.25)

def extract_no_incidents_text(soup: BeautifulSoup) -> str:
    full = collapse_ws(soup.get_text(" ", strip=True))
    m = NO_INCIDENTS_TODAY_RE.search(full)
    return m.group(0) if m else "No incidents reported today."

# ---------- Extraer arrays sspDataInfo de <script> ----------

def _extract_json_array_from_key(script_text: str, key: str) -> Optional[str]:
    m = re.search(rf"{re.escape(key)}\s*[:=]\s*(\[)", script_text)
    if not m:
        return None
    start = m.start(1)
    depth = 0
    i = start
    while i < len(script_text):
        ch = script_text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return script_text[start:i+1]
        i += 1
    return None

def find_ssp_data_info_arrays(html: str) -> List[str]:
    out: List[str] = []
    soup = BeautifulSoup(html, "lxml")
    for sc in soup.find_all("script"):
        txt = sc.string or sc.get_text() or ""
        if "sspDataInfo" in txt:
            stxt = htmlmod.unescape(txt)
            arr_txt = _extract_json_array_from_key(stxt, "sspDataInfo")
            if arr_txt:
                out.append(arr_txt)
    return out

def parse_ssp_records_for_product(html: str, product_name: str) -> List[Dict[str, Any]]:
    """
    Devuelve lista de dicts SOLO del producto indicado:
    { id, status(int), status_text, subject, otherImpact, hisDate(UTC), productEnName }
    """
    arrays = find_ssp_data_info_arrays(html)
    records: List[Dict[str, Any]] = []
    for arr_txt in arrays:
        data = None
        try:
            data = json.loads(arr_txt)
        except Exception:
            # tolerancia a JSON "imperfecto"
            try:
                cleaned = re.sub(r",\s*}", "}", arr_txt)
                cleaned = re.sub(r",\s*]", "]", cleaned)
                data = json.loads(cleaned)
            except Exception:
                continue

        for item in data:
            prod = str(item.get("productEnName") or "").strip()
            if prod != product_name:
                continue

            _id = str(item.get("id") or item.get("incidentId") or item.get("caseId") or "")
            if not _id:
                continue

            status = item.get("status")
            try:
                status = int(status)
            except Exception:
                status = None
            status_text = STATUS_MAP.get(status, "Update")

            subject = unquote(str(item.get("subject") or item.get("title") or "Incident")).strip()
            other = unquote(str(item.get("otherImpact") or item.get("impact") or "")).strip()

            raw_date = item.get("hisDate") or item.get("dateTime") or item.get("createdDate")
            dt_utc = None
            if raw_date:
                try:
                    dt = dtparser.parse(str(raw_date))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt_utc = dt.astimezone(timezone.utc)
                except Exception:
                    dt_utc = None
            if not dt_utc:
                continue

            records.append({
                "id": _id,
                "productEnName": prod,
                "status": status,
                "status_text": status_text,
                "subject": subject,
                "otherImpact": other,
                "hisDate": dt_utc,
            })
    return records

# ---------- Solo HOY ----------

def is_today_utc(dtobj: datetime) -> bool:
    now = datetime.utcnow()
    return (dtobj.year, dtobj.month, dtobj.day) == (now.year, now.month, now.day)

def summarize_today(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Agrupa por 'id' y toma la última actualización de HOY para cada incidente.
    Devuelve: { "count": N, "items": ["• Resolved — Title (HH:MM UTC)", ...] }
    """
    today_updates = [r for r in records if is_today_utc(r["hisDate"])]
    if not today_updates:
        return {"count": 0, "items": []}

    by_id: Dict[str, List[Dict[str, Any]]] = {}
    for r in today_updates:
        by_id.setdefault(r["id"], []).append(r)

    lines: List[str] = []
    for inc_id, items in by_id.items():
        items.sort(key=lambda x: x["hisDate"], reverse=True)
        last = items[0]
        title = last["subject"] or "Incident"
        hhmm = last["hisDate"].strftime("%H:%M UTC")
        status_word = last["status_text"]
        lines.append(f"• {status_word} — {title} ({hhmm})")

    # Orden descendente lexicográfica (hora incluida en el string)
    lines.sort(reverse=True)
    return {"count": len(lines), "items": lines}

# ---------- Formateo de sección por producto ----------

def build_section_lines(name: str, html: str, product: str) -> Tuple[List[str], int]:
    records = parse_ssp_records_for_product(html, product)
    today = summarize_today(records)

    lines = [f"[{name}]"]
    if today["count"] > 0:
        lines.append(f"Incidents today — {today['count']} incident(s)")
        lines.extend(today["items"])
    else:
        soup = BeautifulSoup(html, "lxml")
        no_msg = extract_no_incidents_text(soup)
        lines.append("Incidents today")
        lines.append(f"- {no_msg}")

    return lines, int(today["count"])

# ---------- Export normalizado para digest ----------

def collect(driver) -> Dict[str, Any]:
    """
    Devuelve un dict normalizado para el digest:
      {
        "name": "Trend Micro",
        "timestamp_utc": "YYYY-MM-DD HH:MM",
        "component_lines": [],
        "incidents_lines": [ "<bloque Cloud One>", "<bloque Vision One>" ],
        "overall_ok": True/False
      }
    """
    sections: List[str] = []
    total_today = 0

    for site in SITES:
        driver.get(site["url"])
        wait_for_page(driver)
        html = driver.page_source

        if SAVE_HTML:
            try:
                with open(f"trend_{site['slug']}_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
            except Exception:
                pass

        lines, cnt = build_section_lines(site["name"], html, site["product"])
        sections.append("\n".join(lines))
        total_today += cnt

    return {
        "name": "Trend Micro",
        "timestamp_utc": _now_utc_clean(),
        "component_lines": [],            # Trend no expone “componentes” en estas páginas
        "incidents_lines": sections,      # cada bloque como párrafo independiente
        "overall_ok": (total_today == 0),
    }

# ---------- Runner (notificación combinada) ----------

def run():
    driver = start_driver()
    try:
        sections: List[str] = []
        for site in SITES:
            driver.get(site["url"])
            wait_for_page(driver)
            html = driver.page_source
            if SAVE_HTML:
                try:
                    with open(f"trend_{site['slug']}_page_source.html", "w", encoding="utf-8") as f:
                        f.write(html)
                except Exception:
                    pass
            lines, _ = build_section_lines(site["name"], html, site["product"])
            sections.append("\n".join(lines))

        msg_lines = [
            "Trend Micro - Status",
            now_utc_str(),
            "",
            "\n\n".join(sections)
        ]
        msg = "\n".join(msg_lines)

        print("\n===== TREND MICRO (COMBINED) =====")
        print(msg)
        print("==================================\n")

        send_telegram(msg)
        send_teams(msg)

    except Exception as e:
        print(f"[trendmicro] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"Trend Micro - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ Trend Micro - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
