# vendors/qualys.py
import os
import re
import traceback
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams
from common.format import header, render_incidents

URL = "https://status.qualys.com/history?filter=8f7fjwhmd4n0"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"
LOOKBACK_DAYS = 15

MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic"
# Ejemplos de la página:
# "Aug 11, 10:01 - 14:00 PDT"
# "Jul 7, 22:31 - Jul 8, 06:30 PDT"
DATE_LINE_RE = re.compile(
    rf"\b({MONTHS})\s+\d{{1,2}},\s+\d{{1,2}}:\d{{2}}\s*-\s*(?:({MONTHS})\s+\d{{1,2}},\s+)?\d{{1,2}}:\d{{2}}\s*(UTC|GMT|[A-Z]{{2,4}})\b",
    re.I,
)
MONTH_YEAR_RE = re.compile(rf"\b({MONTHS})\s+(\d{{4}})\b", re.I)

def wait_for_page(driver):
    # Esperamos a que cargue algo representativo (botón de filtro o tarjetas con enlaces)
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
            # Si no trae tz, asumimos UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def nearest_month_year(node):
    """Busca el h2/h3 'August 2025' más cercano hacia arriba/atrás."""
    cur = node
    # 1) mirar ancestros y hermanos previos
    for _ in range(10):
        # hermanos previos
        sib = getattr(cur, "previous_sibling", None)
        while sib:
            if getattr(sib, "get_text", None):
                txt = sib.get_text(strip=True)
                m = MONTH_YEAR_RE.search(txt or "")
                if m:
                    return m.group(1), int(m.group(2))
            sib = getattr(sib, "previous_sibling", None)
        # ancestro
        cur = getattr(cur, "parent", None)
        if not cur:
            break
        if getattr(cur, "get_text", None):
            txt = cur.get_text(" ", strip=True)
            m = MONTH_YEAR_RE.search(txt or "")
            if m:
                return m.group(1), int(m.group(2))
    return None, None

def parse_date_range(line_text: str, node_for_context) -> tuple:
    """
    Convierte:
        'Aug 11, 10:01 - 14:00 PDT'
        'Jul 7, 22:31 - Jul 8, 06:30 PDT'
    a (start_utc, end_utc)
    """
    m = DATE_LINE_RE.search(line_text or "")
    if not m:
        return None, None

    # tz va al final; si no aparece, lo intenta dateutil igualmente
    tz = m.group(3) or "UTC"
    left = line_text[: m.end()].split("-")[0].strip().rstrip(",")
    right = line_text[: m.end()].split("-")[1].strip()

    # ¿Tenemos año contextual?
    mon_ctx, year_ctx = nearest_month_year(node_for_context)

    # Normalizamos cadenas start/end
    start_str = left
    if not re.search(r"\b(UTC|GMT|[A-Z]{2,4})\b", start_str, flags=re.I):
        start_str += f" {tz}"
    if year_ctx and not re.search(r"\b\d{4}\b", start_str):
        start_str += f" {year_ctx}"

    # right puede tener solo hora o fecha+hora
    if re.search(rf"\b({MONTHS})\s+\d{{1,2}},", right, flags=re.I):
        end_str = right
    else:
        # reutilizamos mes/día de 'left'
        md = re.match(rf"\b({MONTHS})\s+(\d{{1,2}}),\s*\d{{1,2}}:\d{{2}}", left, flags=re.I)
        if md:
            end_str = f"{md.group(1)} {md.group(2)}, {right}"
        else:
            end_str = right
    if not re.search(r"\b(UTC|GMT|[A-Z]{2,4})\b", end_str, flags=re.I):
        end_str += f" {tz}"
    if year_ctx and not re.search(r"\b\d{4}\b", end_str):
        end_str += f" {year_ctx}"

    return parse_dt_utc(start_str), parse_dt_utc(end_str)

def is_card_container(node):
    """Heurística: un contenedor de tarjeta suele tener un <a> de título y una línea con fecha."""
    if not getattr(node, "get_text", None):
        return False
    txt = node.get_text(" ", strip=True)
    has_date = DATE_LINE_RE.search(txt or "") is not None
    has_link = bool(node.select("a[href]"))
    return has_date and has_link

def collect_cards(soup: BeautifulSoup):
    # Buscar bloques candidatos (divs con un <a> y una línea de fecha)
    cards = []
    for div in soup.find_all("div"):
        try:
            if is_card_container(div):
                cards.append(div)
        except Exception:
            continue
    # fallback: si no encontró, usa anchors visibles con fecha en ancestros cercanos
    if not cards:
        for a in soup.select("a[href]"):
            parent = a
            for _ in range(4):
                parent = getattr(parent, "parent", None)
                if not parent:
                    break
                if is_card_container(parent):
                    cards.append(parent)
                    break
    return cards

def extract_incidents(cards):
    incidents = []
    for card in cards:
        # Título del anchor principal
        a = None
        for cand in card.select("a[href]"):
            t = cand.get_text(" ", strip=True) or ""
            # ignorar navegación conocida
            if re.search(r"Subscribe To Updates|Support|Filter Components|Proofpoint|Qualys|Login|Log in|Terms|Privacy|Guest", t, re.I):
                continue
            # el título de evento suele ser el anchor más largo
            if not a or len(t) > len(a.get_text(" ", strip=True) or ""):
                a = cand
        if not a:
            continue

        title = a.get_text(" ", strip=True)
        if title.startswith("[Scheduled]"):
            # pedido: ignorar todo lo programado
            continue

        # Estado: si viene entre corchetes iniciales (p.ej., [Investigating]), tómalo. Si no, 'Update'
        m_br = re.match(r"\[(.*?)\]\s*(.+)", title)
        status = "Update"
        if m_br and m_br.group(1).strip():
            status = m_br.group(1).strip()
            title = m_br.group(2).strip()

        href = a.get("href", "")
        url = href if href.startswith("http") else f"https://status.qualys.com{href}" if href.startswith("/") else href

        # Línea de fecha dentro del card
        card_text = card.get_text("\n", strip=True)
        m_line = DATE_LINE_RE.search(card_text or "")
        started_at = ended_at = None
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

    # History → tratamos todo como “pasados”; filtramos por 15 días
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)

    def in_lookback(inc):
        dt = inc.get("ended_at") or inc.get("started_at")
        if not dt:
            return True  # si no hay fecha, lo consideramos dentro
        return dt >= cutoff

    pasados_15 = [i for i in items if in_lookback(i)]
    activos = []  # esta URL es de histórico; los activos van en otra vista
    return activos, pasados_15

def run():
    driver = start_driver()
    try:
        activos, pasados = analizar_qualys(driver)
        resumen = header("Qualys") + "\n" + render_incidents(activos, pasados)
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
