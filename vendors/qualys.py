# vendors/qualys.py
# -*- coding: utf-8 -*-
"""
Qualys — History:
- Página: https://status.qualys.com/history?filter=8f7fjwhmd4n0
- Muestra incidencias históricas por meses.
- Reglas:
  * Ignorar entradas [Scheduled] / scheduled maintenance.
  * Convertir horas a UTC.
  * Salida de texto plano (sin HTML).
  * Proveer collect(driver) para el digest.
"""

import os
import re
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams

URL = "https://status.qualys.com/history?filter=8f7fjwhmd4n0"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# Meses abreviados + meses completos (p.ej. "June 2025")
MONTHS_SHORT = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
MONTHS_FULL = "January|February|March|April|May|June|July|August|September|October|November|December"

# Rangos horarios (laxos) tipo:
# "Jun 13, 09:18 - Jun 14, 11:18 PDT"  o  "Jun 2, 05:19 - 05:44 PDT"
DATE_RANGE_RE = re.compile(
    rf"\b({MONTHS_SHORT})\s+\d{{1,2}}\s*,\s*\d{{1,2}}:\d{{2}}\s*[-–]\s*(?:({MONTHS_SHORT})\s+\d{{1,2}}\s*,\s*)?\d{{1,2}}:\d{{2}}\s*(UTC|GMT|[A-Z]{{2,4}})\b",
    re.I,
)
# Encabezado de mes: "June 2025"
MONTH_HEADER_RE = re.compile(rf"\b({MONTHS_FULL})\s+(\d{{4}})\b", re.I)

# Mapa TZ abreviado → offset en minutos
TZ_OFFSETS_MIN = {
    "UTC": 0, "GMT": 0,
    "PDT": -7*60, "PST": -8*60,
    "EDT": -4*60, "EST": -5*60,
    "CDT": -5*60, "CST": -6*60,
    "MDT": -6*60, "MST": -7*60,
    "CEST": 120, "CET": 60,
    "BST": 60,
}

# ------------------ Utilidades básicas ------------------

def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def now_utc_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _now_utc_clean() -> str:
    """Para export JSON: sin el sufijo 'UTC'; el renderer lo añadirá si procede."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def wait_for_page(driver):
    # Espera a que haya enlaces y que aparezca algún rango horario en el body (render dinámico)
    WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href]")))
    for _ in range(40):
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if DATE_RANGE_RE.search(_collapse_ws(body_text)):
            return
        time.sleep(0.4)

def _norm_node_text(node) -> str:
    try:
        return _collapse_ws(node.get_text(" ", strip=True))
    except Exception:
        return ""

def _find_year_context(node) -> Optional[int]:
    """Busca hacia atrás el encabezado 'June 2025' más cercano para obtener el año."""
    from bs4.element import NavigableString
    # Hacia atrás en el flujo
    for prev in node.previous_elements:
        txt = _collapse_ws(prev if isinstance(prev, str) else getattr(prev, "get_text", lambda *a,**k: "")(" ", strip=True))
        m = MONTH_HEADER_RE.search(txt or "")
        if m:
            try:
                return int(m.group(2))
            except Exception:
                pass
    # Ancestros
    anc = node
    for _ in range(8):
        if not anc:
            break
        txt = _norm_node_text(anc)
        m = MONTH_HEADER_RE.search(txt or "")
        if m:
            try:
                return int(m.group(2))
            except Exception:
                pass
        anc = getattr(anc, "parent", None)
    return None

def _parse_with_tz_abbrev(s_no_tz: str, tzabbr: str) -> Optional[datetime]:
    """Convierte 'Jun 13, 2025 09:18' con tz 'PDT' a UTC usando el mapa."""
    try:
        dt = datetime.strptime(s_no_tz, "%b %d, %Y %H:%M")
    except Exception:
        return None
    offset = TZ_OFFSETS_MIN.get((tzabbr or "").upper())
    if offset is None:
        return None
    tzinfo = timezone(timedelta(minutes=offset))
    return dt.replace(tzinfo=tzinfo).astimezone(timezone.utc)

def _build_dt_strings(part: str, year: int) -> Optional[str]:
    """
    Normaliza 'Jun 13 , 09:18' -> 'Jun 13, 2025 09:18' (sin TZ).
    """
    part = _collapse_ws(part)
    part = re.sub(r"\s*,\s*", ", ", part)
    m = re.match(rf"({MONTHS_SHORT})\s+(\d{{1,2}}),\s*(\d{{1,2}}:\d{{2}})", part, flags=re.I)
    if not m:
        return None
    mon, day, hm = m.groups()
    return f"{mon} {day}, {year} {hm}"

def _parse_date_range(date_text: str, context_node):
    """
    'Jun 13 , 09:18 - Jun 14 , 11:18 PDT' -> (start_utc, end_utc)
    Usa el año del encabezado más cercano; si no, año UTC actual.
    """
    date_text = _collapse_ws(date_text)
    m = DATE_RANGE_RE.search(date_text or "")
    if not m:
        return None, None
    tzabbr = m.group(3)
    # Divide por '-' o '–'
    parts = re.split(r"\s*[-–]\s*", m.group(0))
    left = (parts[0] or "").strip().rstrip(",")
    right = (parts[1] or "").strip()
    # Si 'right' no tiene mes/día, hereda del 'left'
    if not re.search(rf"({MONTHS_SHORT})\s+\d{{1,2}}", right, flags=re.I):
        md = re.match(rf"({MONTHS_SHORT})\s+\d{{1,2}}", left, flags=re.I)
        if md:
            right = f"{md.group(0)}, {right}"

    year = _find_year_context(context_node) or datetime.utcnow().year
    left_s  = _build_dt_strings(left, year)
    right_s = _build_dt_strings(right, year)
    sdt = _parse_with_tz_abbrev(left_s, tzabbr)  if left_s  else None
    edt = _parse_with_tz_abbrev(right_s, tzabbr) if right_s else None
    return sdt, edt

def _is_scheduled(text: str) -> bool:
    t = (text or "").lower()
    return "[scheduled]" in t or "scheduled maintenance" in t

def _status_from_text(text: str) -> str:
    low = (text or "").lower()
    if "has been resolved" in low or re.search(r"\bresolved\b", low):
        return "Resolved"
    if "mitigated" in low:
        return "Mitigated"
    if "service disruption" in low or "degraded" in low or "impact" in low:
        return "Incident"
    return "Update"

# ------------------ Extracción ------------------

def _extract_items(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    # 1) Candidatos: <div> cuyo texto NORMALIZADO contenga EXACTAMENTE un rango horario
    candidates = []
    for div in soup.find_all("div"):
        txt = _norm_node_text(div)
        matches = list(DATE_RANGE_RE.finditer(txt))
        if len(matches) == 1:
            candidates.append((div, txt, matches[0].group(0)))

    # 2) Filtra por tarjeta (no contenedor de mes), descarta [Scheduled], saca título/url/fechas
    for div, txt, date_str in candidates:
        if _is_scheduled(txt):
            continue

        # Heurística: si un ancestro cercano también tiene exactamente 1 rango, es contenedor -> saltar
        anc = div.parent
        is_container = False
        for _ in range(6):
            if not anc or getattr(anc, "name", None) != "div":
                break
            anc_txt = _norm_node_text(anc)
            if len(list(DATE_RANGE_RE.finditer(anc_txt))) == 1:
                is_container = True
                break
            anc = anc.parent
        if is_container:
            continue

        # Título: anchor cuyo texto aparezca ANTES de la fecha y sea el más largo
        anchors = div.find_all("a", href=True)
        best_a = None
        best_len = 0
        pos_date = txt.find(date_str) if date_str in txt else -1
        for a in anchors:
            t = _collapse_ws(a.get_text(" ", strip=True))
            if not t:
                continue
            if re.search(r"Subscribe To Updates|Support|Filter Components|Qualys|Login|Log in|Terms|Privacy|Guest", t, re.I):
                continue
            pos_title = txt.find(t)
            if pos_date != -1 and pos_title != -1 and pos_title < pos_date and len(t) > best_len:
                best_a = a
                best_len = len(t)

        if best_a:
            title = _collapse_ws(best_a.get_text(" ", strip=True))
            href = best_a.get("href", "")
            url = href if href.startswith("http") else f"https://status.qualys.com{href}" if href.startswith("/") else href
        else:
            # Fallback: primera línea válida previa a la fecha (evita frases de estado y scheduled)
            raw_lines = [ln.strip() for ln in (div.get_text("\n", strip=True) or "").split("\n")]
            acc = []
            for ln in raw_lines:
                if DATE_RANGE_RE.search(_collapse_ws(ln)):
                    break
                if _is_scheduled(ln) or re.search(r"has been resolved|has been mitigated|has been completed", ln, re.I):
                    continue
                if ln:
                    acc.append(ln)
            if not acc:
                continue
            title = _collapse_ws(acc[0])
            url = None

        # Fechas (UTC)
        started_at, ended_at = _parse_date_range(date_str, div)

        items.append({
            "title": title,
            "status": _status_from_text(txt),
            "url": url,
            "started_at": started_at,
            "ended_at": ended_at,
            "raw_text": txt,
        })

    # Ordena por fin/inicio desc
    def sort_key(i):
        return (
            i.get("ended_at") or i.get("started_at") or datetime.min.replace(tzinfo=timezone.utc),
            i.get("title") or "",
        )
    return sorted(items, key=sort_key, reverse=True)

# ------------------ Formateo (texto plano) ------------------

def _fmt_item_lines(idx: int, inc: Dict[str, Any]) -> List[str]:
    t = inc.get("title") or "Sin título"
    u = inc.get("url")
    st = inc.get("status") or "Update"
    sdt = inc.get("started_at")
    edt = inc.get("ended_at")
    s_s = sdt.strftime("%Y-%m-%d %H:%M UTC") if sdt else "N/D"
    e_s = edt.strftime("%Y-%m-%d %H:%M UTC") if edt else "N/D"
    title_line = f"{idx}. {t}" if not u else f"{idx}. {t} ({u})"
    detail_line = f"   Estado: {st} · Inicio: {s_s} · Fin: {e_s}"
    return [title_line, detail_line]

def format_message(items: List[Dict[str, Any]]) -> str:
    lines: List[str] = [
        "Qualys - Estado de Incidentes",
        now_utc_str(),
        "",
        "Histórico (meses visibles en la página)"
    ]
    if not items:
        lines.append("- No hay incidencias no programadas en los meses mostrados.")
    else:
        for idx, inc in enumerate(items, 1):
            lines.extend(_fmt_item_lines(idx, inc))
    return "\n".join(lines)

# ------------------ Export normalizado (digest) ------------------

def _format_incidents_lines_for_digest(items: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = ["Histórico (meses visibles en la página)"]
    if not items:
        lines.append("- No hay incidencias no programadas en los meses mostrados.")
        return lines
    for idx, inc in enumerate(items, 1):
        lines.extend(_fmt_item_lines(idx, inc))
    return lines

def collect(driver) -> Dict[str, Any]:
    """
    Devuelve un dict normalizado para el digest:
      {
        "name": "Qualys",
        "timestamp_utc": "YYYY-MM-DD HH:MM",
        "component_lines": [],
        "incidents_lines": [...],
        "overall_ok": True/False
      }
    """
    driver.get(URL)
    wait_for_page(driver)
    time.sleep(0.4)

    html = driver.page_source
    if SAVE_HTML:
        try:
            with open("qualys_page_source.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

    soup = BeautifulSoup(html, "lxml")
    items = _extract_items(soup)

    return {
        "name": "Qualys",
        "timestamp_utc": _now_utc_clean(),
        "component_lines": [],                    # Qualys no expone "componentes" aquí
        "incidents_lines": _format_incidents_lines_for_digest(items),
        "overall_ok": len(items) == 0,            # si hay items no programados, overall_ok = False
    }

# ------------------ Runner clásico (notificación) ------------------

def run():
    driver = start_driver()
    try:
        driver.get(URL)
        wait_for_page(driver)

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("qualys_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML guardado en qualys_page_source.html")
            except Exception as e:
                print(f"No se pudo guardar HTML: {e}")

        soup = BeautifulSoup(html, "lxml")
        items = _extract_items(soup)
        resumen = format_message(items)

        print("\n===== QUALYS =====")
        print(resumen)
        print("==================\n")

        send_telegram(resumen)
        send_teams(resumen)

    except Exception as e:
        print(f"[qualys] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"Qualys - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ Qualys - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
