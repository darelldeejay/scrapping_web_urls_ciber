# vendors/qualys.py
import os
import re
import time
import traceback
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams
from common.format import header

URL = "https://status.qualys.com/history?filter=8f7fjwhmd4n0"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic"
MONTHS_FULL = "January|February|March|April|May|June|July|August|September|October|November|December"

# Acepta '-' o '–' y TZ de 2-4 letras (PDT, CEST, UTC, etc.)
DATE_LINE_RE = re.compile(
    rf"\b({MONTHS})\s+\d{{1,2}},\s+\d{{1,2}}:\d{{2}}\s*[-–]\s*(?:({MONTHS})\s+\d{{1,2}},\s+)?\d{{1,2}}:\d{{2}}\s*(UTC|GMT|[A-Z]{{2,4}})\b",
    re.I,
)
# Encabezado de mes: "June 2025"
MONTH_HEADER_RE = re.compile(rf"^\s*({MONTHS_FULL})\s+(\d{{4}})\s*$", re.I)


def wait_for_page(driver):
    # Espera a que existan enlaces y luego a que el body contenga una línea de fecha
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "a[href]"))
    )
    # Espera activa a que aparezca un patrón de fecha en el texto de la página
    for _ in range(20):
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if DATE_LINE_RE.search(body_text):
            return
        time.sleep(0.5)


def parse_dt_utc(s: str):
    try:
        dt = dateparser.parse(s, fuzzy=True)
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_date_range_with_year(line_text: str, year_ctx: int | None):
    """Convierte 'Jun 13, 09:18 - Jun 14, 11:18 PDT' en (start_utc, end_utc) usando año de contexto."""
    m = DATE_LINE_RE.search(line_text or "")
    if not m:
        return None, None

    tz = m.group(3) or "UTC"
    parts = re.split(r"\s*[-–]\s*", m.group(0))
    left = (parts[0] or "").strip().rstrip(",")
    right = (parts[1] or "").strip()

    start_str = left
    if not re.search(r"\b(UTC|GMT|[A-Z]{2,4})\b", start_str, flags=re.I):
        start_str += f" {tz}"
    if year_ctx and not re.search(r"\b\d{4}\b", start_str):
        start_str += f" {year_ctx}"

    if re.search(rf"\b({MONTHS})\s+\d{{1,2}},", right, flags=re.I):
        end_str = right
    else:
        md = re.match(rf"\b({MONTHS})\s+(\d{{1,2}}),\s*\d{{1,2}}:\d{{2}}", left, flags=re.I)
        end_str = f"{md.group(1)} {md.group(2)}, {right}" if md else right

    if not re.search(r"\b(UTC|GMT|[A-Z]{2,4})\b", end_str, flags=re.I):
        end_str += f" {tz}"
    if year_ctx and not re.search(r"\b\d{4}\b", end_str):
        end_str += f" {year_ctx}"

    return parse_dt_utc(start_str), parse_dt_utc(end_str)


def qualys_status_from_text(text: str) -> str:
    low = (text or "").lower()
    if "has been resolved" in low or re.search(r"\bresolved\b", low):
        return "Resolved"
    if "has been mitigated" in low or "mitigated" in low:
        return "Mitigated"
    if "service disruption" in low or "degraded" in low or "impact" in low:
        return "Incident"
    return "Update"


def anchor_before_date(card: BeautifulSoup, date_text: str):
    """Devuelve el <a> que aparece ANTES de la línea de fecha dentro del card."""
    last_a = None
    reached_date = False
    for el in card.descendants:
        if isinstance(el, str):
            if date_text and el.strip() and date_text in el:
                reached_date = True
                break
            continue
        if getattr(el, "name", None) == "a" and el.has_attr("href"):
            t = el.get_text(" ", strip=True) or ""
            if not t:
                continue
            if re.search(r"Subscribe To Updates|Support|Filter Components|Qualys|Login|Log in|Terms|Privacy|Guest", t, re.I):
                continue
            last_a = el
    return last_a


def find_cards_dom(soup: BeautifulSoup):
    """
    Busca divs que contengan exactamente UNA línea de fecha (card),
    evitando ancestros demasiado grandes (mes completo).
    """
    def count_date_lines(node) -> int:
        try:
            txt = node.get_text(" ", strip=True)
            return len(re.findall(DATE_LINE_RE, txt or ""))
        except Exception:
            return 0

    candidates = []
    for div in soup.find_all("div"):
        if count_date_lines(div) == 1:
            # descarta si algún ancestro cercano también tiene exactamente 1 (contendor de mes)
            anc = div.parent
            too_big = False
            for _ in range(6):
                if not anc or getattr(anc, "name", None) != "div":
                    break
                if count_date_lines(anc) == 1:
                    too_big = True
                    break
                anc = anc.parent
            if not too_big:
                candidates.append(div)

    # dedup
    seen = set()
    out = []
    for c in candidates:
        if id(c) not in seen:
            seen.add(id(c))
            out.append(c)
    return out


def fallback_cards_from_lines(soup: BeautifulSoup):
    """
    Fallback por texto puro:
    - Recorre líneas.
    - Mantiene el año del encabezado 'June 2025'.
    - Cuando ve una línea de fechas, toma como título la primera línea
      previa válida (no Scheduled ni frases de estado).
    """
    text = soup.get_text("\n", strip=True)
    lines = [ln for ln in text.split("\n")]
    items = []
    current_year = None

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Captura encabezado de mes -> año de contexto
        mh = MONTH_HEADER_RE.match(line)
        if mh:
            current_year = int(mh.group(2))
            i += 1
            continue

        m = DATE_LINE_RE.search(line)
        if not m:
            i += 1
            continue

        # Tenemos una línea de fecha; buscamos título hacia atrás
        title = None
        back = i - 1
        while back >= 0 and (i - back) <= 6:  # mira hasta 6 líneas atrás
            cand = lines[back].strip()
            if not cand:
                back -= 1
                continue
            if cand.startswith("[Scheduled]") or "scheduled maintenance" in cand.lower():
                title = None  # card programado -> descartar
                break
            if re.search(r"has been resolved|has been mitigated|has been completed", cand, re.I):
                back -= 1
                continue
            # Evita encabezados tipo "June 2025"
            if MONTH_HEADER_RE.match(cand):
                back -= 1
                continue
            title = cand
            break

        if title:
            # Busca un href cuyo texto coincida (si existe)
            url = None
            a = soup.find("a", string=re.compile(re.escape(title), re.I))
            if a and a.has_attr("href"):
                href = a.get("href", "")
                url = href if href.startswith("http") else f"https://status.qualys.com{href}" if href.startswith("/") else href

            start, end = parse_date_range_with_year(line, current_year)
            items.append({
                "title": title,
                "status": qualys_status_from_text("\n".join(lines[max(0, back): i+1])),
                "url": url,
                "started_at": start,
                "ended_at": end,
                "raw_text": "\n".join(lines[max(0, back): i+1]),
            })
        i += 1

    # filtra programados por si se coló alguno
    final = []
    for it in items:
        raw = (it.get("raw_text") or "").lower()
        if "[scheduled]" in raw or "scheduled maintenance" in raw:
            continue
        final.append(it)
    return final


def analizar_qualys(driver):
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

    # 1) Intento por DOM (cards con 1 línea de fecha)
    items = []
    for card in find_cards_dom(soup):
        card_text = card.get_text("\n", strip=True)

        # Ignora programados a nivel de card
        if "[Scheduled]" in card_text or "scheduled maintenance" in card_text.lower():
            continue

        # Año de contexto desde encabezado cercano
        year_ctx = None
        anc = card
        for _ in range(8):
            if not anc:
                break
            txt = anc.get_text(" ", strip=True)
            mhy = MONTH_HEADER_RE.search(txt or "")
            if mhy:
                year_ctx = int(mhy.group(2))
                break
            anc = getattr(anc, "parent", None)

        # fecha (primer match del card)
        m_line = DATE_LINE_RE.search(card_text or "")
        started_at = ended_at = None
        date_line = None
        if m_line:
            date_line = m_line.group(0)
            started_at, ended_at = parse_date_range_with_year(date_line, year_ctx)

        # Título + URL (ancla antes de la fecha)
        title = None
        url = None
        if date_line:
            a = anchor_before_date(card, date_line)
            if a:
                title = a.get_text(" ", strip=True)
                href = a.get("href", "")
                url = href if href.startswith("http") else f"https://status.qualys.com{href}" if href.startswith("/") else href

        if not title:
            # Fallback: primera línea previa válida
            lines = [ln.strip() for ln in (card_text or "").split("\n") if ln.strip()]
            for ln in lines:
                if DATE_LINE_RE.search(ln):
                    break
                if ln.startswith("[Scheduled]") or "scheduled maintenance" in ln.lower():
                    continue
                if re.search(r"has been resolved|has been mitigated|has been completed", ln, re.I):
                    continue
                title = ln
                break

        if title:
            items.append({
                "title": title,
                "status": qualys_status_from_text(card_text),
                "url": url,
                "started_at": started_at,
                "ended_at": ended_at,
                "raw_text": card_text,
            })

    # 2) Fallback por líneas si no hay nada
    if not items:
        items = fallback_cards_from_lines(soup)

    # Ordenamos por fin/inicio desc
    def sort_key(i):
        return (
            i.get("ended_at") or i.get("started_at") or datetime.min.replace(tzinfo=timezone.utc),
            i.get("title") or "",
        )
    return sorted(items, key=sort_key, reverse=True)


def format_message(items):
    lines = [header("Qualys"), "\n<b>Histórico (meses visibles en la página)</b>"]
    if not items:
        lines.append("\n- No hay incidencias no programadas en los meses mostrados.")
        return "\n".join(lines)

    for idx, inc in enumerate(items, 1):
        t = inc.get("title") or "Sin título"
        u = inc.get("url")
        st = inc.get("status") or "Update"
        sdt = inc.get("started_at")
        edt = inc.get("ended_at")
        s_s = sdt.strftime("%Y-%m-%d %H:%M UTC") if sdt else "N/D"
        e_s = edt.strftime("%Y-%m-%d %H:%M UTC") if edt else "N/D"
        title_line = f"{idx}. {t}" if not u else f'{idx}. <a href="{u}">{t}</a>'
        lines.append(title_line)
        lines.append(f"   Estado: {st} · Inicio: {s_s} · Fin: {e_s}")
    return "\n".join(lines)


def run():
    driver = start_driver()
    try:
        items = analizar_qualys(driver)
        resumen = format_message(items)
        print("\n===== QUALYS =====")
        print(resumen)
        print("==================\n")
        send_telegram(resumen)
        send_teams(resumen)
    except Exception as e:
        print(f"[qualys] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"<b>Qualys - Monitor</b>\nSe produjo un error:\n<pre>{str(e)}</pre>")
        send_teams(f"❌ Qualys - Monitor\nSe produjo un error: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
