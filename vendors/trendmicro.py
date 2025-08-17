# vendors/trendmicro.py
import os
import re
import time
import html as htmlmod
import json
import traceback
from datetime import datetime, timezone
from urllib.parse import unquote

from bs4 import BeautifulSoup
from dateutil import parser as dtparser, tz
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

# Palabras por si hace falta fallback textual
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

# Map de códigos de estado que aparecen en sspDataInfo
STATUS_MAP = {
    770060000: "Resolved",
    770060001: "Monitoring",
    770060002: "Investigating",
    770060003: "Identified",
    770060004: "Update",
    770060005: "Mitigated",
}

def now_utc_str():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver):
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    # Espera a que aparezca el bloque de incidentes o texto de no-incidentes
    for _ in range(50):
        body = driver.find_element(By.TAG_NAME, "body").text
        text = collapse_ws(body)
        if ("past incidents" in text.lower()) or NO_INCIDENTS_TODAY_RE.search(text) or "sspDataInfo" in driver.page_source:
            return
        time.sleep(0.3)

# ============= Extracción del array sspDataInfo desde los <script> =============

def _extract_json_array_from_key(script_text: str, key: str):
    """
    Busca `key` seguido de '=' o ':' y devuelve el JSON array que le sigue, si lo encuentra.
    Robustez: hace un emparejador de corchetes para extraer [ ... ] aún con comas/objetos dentro.
    """
    m = re.search(rf"{re.escape(key)}\s*[:=]\s*(\[)", script_text)
    if not m:
        return None
    start = m.start(1)
    # scan bracket depth
    depth = 0
    i = start
    while i < len(script_text):
        ch = script_text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                # inclusive slice [start:i+1]
                arr_txt = script_text[start:i+1]
                return arr_txt
        i += 1
    return None

def find_ssp_data_info_arrays(html: str):
    """
    Devuelve lista de arrays JSON (como texto) encontrados en scripts que contengan 'sspDataInfo'.
    """
    out = []
    soup = BeautifulSoup(html, "lxml")
    for sc in soup.find_all("script"):
        txt = sc.string or sc.get_text() or ""
        if "sspDataInfo" in txt:
            # desescapa HTML entities por si el JSON está escapado
            stxt = htmlmod.unescape(txt)
            arr_txt = _extract_json_array_from_key(stxt, "sspDataInfo")
            if arr_txt:
                out.append(arr_txt)
    return out

def parse_ssp_records(html: str):
    """
    Parsea todos los arrays sspDataInfo y devuelve una lista de dicts normalizados:
    {
      "id": str,
      "status": int,
      "status_text": str,
      "subject": str,
      "otherImpact": str or "",
      "hisDate": datetime (UTC)
    }
    """
    arrays = find_ssp_data_info_arrays(html)
    records = []
    for arr_txt in arrays:
        try:
            data = json.loads(arr_txt)
        except Exception:
            # Intenta limpiar comas colgantes u otros restos menores
            cleaned = re.sub(r",\s*}", "}", arr_txt)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            data = json.loads(cleaned)
        for item in data:
            # Campos posibles (con defensiva por si cambian nombres)
            _id = str(item.get("id") or item.get("incidentId") or item.get("caseId") or "")
            status = item.get("status")
            try:
                status = int(status)
            except Exception:
                status = None
            status_text = STATUS_MAP.get(status, "Update")

            subject = unquote(str(item.get("subject") or item.get("title") or "Incident")).strip()
            other = unquote(str(item.get("otherImpact") or item.get("impact") or "")).strip()

            # hisDate puede venir en ISO/Z; lo normalizamos a UTC
            raw_date = item.get("hisDate") or item.get("dateTime") or item.get("createdDate")
            dt_utc = None
            if raw_date:
                try:
                    dt = dtparser.parse(str(raw_date))
                    if dt.tzinfo is None:
                        # si está naive, asumimos UTC
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt_utc = dt.astimezone(timezone.utc)
                except Exception:
                    dt_utc = None

            if not dt_utc:
                # Si no se pudo parsear, descarta (no nos sirve para filtrar por "hoy")
                continue

            records.append({
                "id": _id,
                "status": status,
                "status_text": status_text,
                "subject": subject,
                "otherImpact": other,
                "hisDate": dt_utc,
            })
    return records

# ==================== Lógica de "solo hoy" y formateo ====================

def is_today_utc(dtobj: datetime) -> bool:
    now = datetime.utcnow()
    return (dtobj.year, dtobj.month, dtobj.day) == (now.year, now.month, now.day)

def summarize_today(records):
    """
    Agrupa por 'id' y toma la última actualización de HOY para cada incidente.
    Devuelve: { "count": N, "items": ["• Resolved — Title (HH:MM UTC)", ...] }
    """
    # Filtrar solo HOY
    today_updates = [r for r in records if is_today_utc(r["hisDate"])]
    if not today_updates:
        return {"count": 0, "items": []}

    # Agrupar por id
    by_id = {}
    for r in today_updates:
        by_id.setdefault(r["id"], []).append(r)

    lines = []
    for inc_id, items in by_id.items():
        # Ordena por hora y toma la última de HOY
        items.sort(key=lambda x: x["hisDate"], reverse=True)
        last = items[0]

        # Titulo base
        title = last["subject"] or "Incident"
        # hora en UTC
        hhmm = last["hisDate"].strftime("%H:%M UTC")

        # Estado textual
        status_word = last["status_text"]
        # Formato final
        # Si hay detalle/impacto y quieres mostrarlo: lo dejamos fuera por concisión.
        lines.append(f"• {status_word} — {title} ({hhmm})")

    # Ordena líneas por hora descendente
    lines.sort(reverse=True)
    return {"count": len(lines), "items": lines}

# ==================== Runner ====================

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

            # 1) Intenta con sspDataInfo (más confiable y completo)
            records = parse_ssp_records(html)

            # 2) Fallback: si no hay sspDataInfo, mirar el día actual por texto (no se notificará si dice "No incidents...")
            today = summarize_today(records)
            if today["count"] == 0:
                soup = BeautifulSoup(html, "lxml")
                full = collapse_ws(soup.get_text(" ", strip=True))
                if NO_INCIDENTS_TODAY_RE.search(full):
                    # Silencioso: no notificar nada (cumple la regla "solo si hay incidentes hoy")
                    print(f"{name}: No incidents reported today.")
                    continue
                # Si no hay array ni texto claro, igualmente no notificamos (evita falsos positivos)
                print(f"{name}: No incidents detected for today (no sspDataInfo entries).")
                continue

            # Hay incidentes hoy en este site → añadimos sección
            any_incidents = True
            lines = [f"[{name}]"]
            if today["count"] > 0:
                lines.append(f"Incidents today — {today['count']} incident(s)")
            for line in today["items"]:
                lines.append(line)
            sections.append("\n".join(lines))

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
            print("Trend Micro: no incidents today in Cloud One or Vision One. No notification sent.")

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
