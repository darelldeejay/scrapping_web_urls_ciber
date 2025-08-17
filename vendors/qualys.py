# vendors/qualys.py
import os
import re
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

# "Aug 11, 10:01 - 14:00 PDT"  |  "Jul 7, 22:31 - Jul 8, 06:30 PDT"
DATE_LINE_RE = re.compile(
    rf"\b({MONTHS})\s+\d{{1,2}},\s+\d{{1,2}}:\d{{2}}\s*-\s*(?:({MONTHS})\s+\d{{1,2}},\s+)?\d{{1,2}}:\d{{2}}\s*(UTC|GMT|[A-Z]{{2,4}})\b",
    re.I,
)
MONTH_YEAR_RE = re.compile(rf"\b({MONTHS})\s+(\d{{4}})\b", re.I)


def wait_for_page(driver):
    targets = [
        (By.XPATH, "//*[contains(., 'Filter Components')]"),
        (By.XPATH, "//*[contains(., 'Subscribe To Updates')]"),
        (By.CSS_SELECTOR, "a[href]"),
    ]
    for by, sel in targets:
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((by, sel)))
            return
        except Exception:
            continue
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))


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


def nearest_month_year(node):
    """Busca el 'August 2025' más cercano hacia arriba/atrás para completar el año en líneas sin año."""
    cur = node
    for _ in range(12):
        sib = getattr(cur, "previous_sibling", None)
        while sib:
            if getattr(sib, "get_text", None):
                txt = sib.get_text(strip=True)
                m = MONTH_YEAR_RE.search(txt or "")
                if m:
                    return m.group(1), int(m.group(2))
            sib = getattr(sib, "previous_sibling", None)
        cur = getattr(cur, "parent", None)
        if not cur:
            break
        if getattr(cur, "get_text", None):
            txt = cur.get_text(" ", strip=True)
            m = MONTH_YEAR_RE.search(txt or "")
            if m:
                return m.group(1), int(m.group(2))
    return None, None


def parse_date_range(line_text: str, node_for_context):
    """Convierte 'Aug 11, 10:01 - 14:00 PDT' a (start_utc, end_utc)."""
    m = DATE_LINE_RE.search(line_text or "")
    if not m:
        return None, None

    tz = m.group(3) or "UTC"
    left = line_text[: m.end()].split("-")[0].strip().rstrip(",")
    right = line_text[: m.end()].split("-")[1].strip()

    mon_ctx, year_ctx = nearest_month_year(node_for_context)

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


def is_card_container(node):
    """Un card válido es cualquier bloque que contenga UNA línea de fecha tipo 'Aug 11, 10:01 - 14:00 PDT'."""
    if not getattr(node, "get_text", None):
        return False
    txt = node.get_text(" ", strip=True)
    return DATE_LINE_RE.search(txt or "") is not None


def collect_cards(soup: BeautifulSoup):
    cards = []
    for div in soup.find_all("div"):
        try:
            if is_card_container(div):
                cards.append(div)
        except Exception:
            continue
    if not cards:
        for el in soup.find_all(string=DATE_LINE_RE):
            node = el.parent
            for _ in range(5):
                node = getattr(node, "parent", None)
                if not node:
                    break
                if is_card_container(node):
                    cards.append(node)
                    break
    # quita duplicados
    seen = set()
    uniq = []
    for c in cards:
        if id(c) not in seen:
            seen.add(id(c))
            uniq.append(c)
    return uniq


def qualys_status_from_text(text: str) -> str:
    low = (text or "").lower()
    if "has been resolved" in low or re.search(r"\bresolved\b", low):
        return "Resolved"
    if "has been mitigated" in low or "mitigated" in low:
        return "Mitigated"
    if "service disruption" in low or "degraded" in low or "impact" in low:
        return "Incident"
    return "Update"


def anchor_before_date(card):
    """Devuelve el <a href> que aparece ANTES de la línea de fecha dentro del card."""
    date_node = card.find(string=DATE_LINE_RE)
    last_a = None
    for el in card.descendants:
        if el == date_node:
            break
        if getattr(el, "name", None) == "a" and el.has_attr("href"):
            t = el.get_text(" ", strip=True) or ""
            if not t:
                continue
            if re.search(r"Subscribe To Updates|Support|Filter Components|Qualys|Login|Log in|Terms|Privacy|Guest", t, re.I):
                continue
            last_a = el
    return last_a


def derive_title(card, card_text: str) -> str:
    """Título por fallback: primera línea relevante antes de la fecha."""
    lines = [ln.strip() for ln in (card_text or "").split("\n") if ln.strip()]
    for ln in lines:
        if DATE_LINE_RE.search(ln):
            break
        if ln.startswith("[Scheduled]") or "scheduled maintenance" in ln.lower():
            continue
        if re.search(r"has been resolved|has been mitigated|has been completed", ln, re.I):
            continue
        return ln
    return "Qualys Incident"


def extract_incidents(cards):
    incidents = []
    for card in cards:
        card_text = card.get_text("\n", strip=True)

        # IGNORAR todo lo programado
        if "[Scheduled]" in card_text or "scheduled maintenance" in card_text.lower():
            continue

        # Título + URL: ancla antes de la fecha si existe
        a = anchor_before_date(card)
        if a:
            title = a.get_text(" ", strip=True)
            href = a.get("href", "")
            url = href if href.startswith("http") else f"https://status.qualys.com{href}" if href.startswith("/") else href
        else:
            title = derive_title(card, card_text)
            url = None

        status = qualys_status_from_text(card_text)

        # Línea de fecha
        started_at = ended_at = None
        m_line = DATE_LINE_RE.search(card_text or "")
        if m_line:
            date_line = m_line.group(0)
            started_at, ended_at = parse_date_range(date_line, card)

        incidents.append({
            "title": title,
            "status": status,
            "url": url,
            "started_at": started_at,
            "ended_at": ended_at,
            "raw_text": card_text,
        })
    return incidents


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
    cards = collect_cards(soup)
    items = extract_incidents(cards)

    # Devolvemos TODO lo visible (histórico por meses), ordenado por fin/inicio
    def sort_key(i):
        return (
            i.get("ended_at") or i.get("started_at") or datetime.min.replace(tzinfo=timezone.utc),
            i.get("title") or "",
        )
    items_sorted = sorted(items, key=sort_key, reverse=True)
    return items_sorted


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
