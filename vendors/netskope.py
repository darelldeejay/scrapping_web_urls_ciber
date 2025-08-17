# vendors/netskope.py
import os
import re
import time
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


# =========================
# Configuración
# =========================
NETSKOPE_URL = "https://trustportal.netskope.com/incidents"
LOOKBACK_DAYS = 15
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"


# =========================
# Helpers de parsing
# =========================
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic"

# Flexible (sin exigir año, con hora opcional)
DATE_REGEX_LOOSE = rf"({MONTHS})\s+\d{{1,2}}(?:,\s*\d{{4}})?(?:\s*,?\s*\d{{1,2}}:\d{{2}}\s*(?:AM|PM)?(?:\s*(?:UTC|GMT|[A-Z]{{2,4}}))?)?"
STATUS_TOKENS = ["Resolved", "Mitigated", "Monitoring", "Identified", "Investigating", "Degraded", "Update"]


def parse_datetime_any(text: str):
    from dateutil import tz
    try:
        dt = dateparser.parse(text, fuzzy=True)
        if dt:
            # normalizamos a UTC
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


def nearest_date_after(label_text: str, full_text: str):
    """Primera fecha tras la ocurrencia de label_text (p.ej., 'Resolved')."""
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


def nearest_date_after_any(labels, text: str):
    for lab in labels:
        dt = nearest_date_after(lab, text)
        if dt:
            return dt
    return None


def latest_status_from_text(text: str):
    """
    Devuelve el estado del ÚLTIMO evento del timeline (en el portal, suele
    estar primero en el bloque de texto).
    """
    low = (text or "").lower()
    candidates = ["update", "mitigated", "monitoring", "identified", "investigating", "degraded", "resolved"]
    positions = []
    for tok in candidates:
        idx = low.find(tok)
        if idx != -1:
            positions.append((idx, tok.title()))
    positions.sort()
    return positions[0][1] if positions else None


def find_nearest_header_date(node):
    """Fecha (p.ej. <h5> 'Aug 15, 2025') más cercana por encima del nodo."""
    cur = node
    steps = 0
    while cur and steps < 15:
        sib = getattr(cur, "previous_sibling", None)
        while sib:
            if getattr(sib, "get_text", None):
                txt = sib.get_text(strip=True)
                dt = parse_datetime_any(txt)
                if dt:
                    return dt
            sib = getattr(sib, "previous_sibling", None)
        cur = getattr(cur, "parent", None)
        steps += 1
    return None


def incident_container_for(node):
    """
    Si el selector nos dio un <a>, asciende al contenedor de la tarjeta que
    contiene la cronología (Resolved/Mitigated/...).
    """
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


def find_section_container(soup: BeautifulSoup, keywords: list[str]):
    heading = None
    for kw in keywords:
        heading = soup.find(
            lambda tag: tag.name in ["h1", "h2", "h3", "h4", "div", "summary"]
            and tag.get_text(strip=True)
            and kw.lower() in tag.get_text(strip=True).lower()
        )
        if heading:
            break
    if not heading:
        return None
    container = heading.find_next_sibling()
    if not container:
        container = heading.parent
    return container


def cards_in_container(container: BeautifulSoup):
    if not container:
        return []
    cards = container.select(".incident, [class*='incident'], a[href*='/incidents/']")
    if cards:
        return cards
    out = []
    for sib in container.next_siblings:
        if not hasattr(sib, "get_text"):
            continue
        if sib.name in ["h1", "h2", "h3", "h4", "summary"]:
            break
        out.extend(sib.select(".incident, [class*='incident'], a[href*='/incidents/']"))
        if out:
            break
    return out


def extract_sections_strict(soup: BeautifulSoup):
    """
    Devuelve (cards_open, cards_past) recorriendo a partir de los headings
    y con fallback global para 'past' si quedara vacío.
    """
    def find_heading(keywords):
        for kw in keywords:
            h = soup.find(
                lambda tag: tag.name in ["h1","h2","h3","h4","div","summary"]
                and tag.get_text(strip=True)
                and kw.lower() in tag.get_text(strip=True).lower()
            )
            if h:
                return h
        return None

    def collect_after(heading, stop_keywords):
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
    """
    Normaliza una tarjeta de incidente:
    - Título: del <a href="/incidents/..."> cuyo texto contiene "Incident <id>".
    - Inicio = Investigating/Identified ; Fin = Resolved (si existe).
    - Estado = ÚLTIMO evento del timeline (lo primero en el bloque).
    """
    container = card
    if getattr(card, "name", None) == "a":
        container = incident_container_for(card)

    # URL + título (preferir enlace principal del incidente)
    url = None
    incident_link = None
    for a in container.find_all("a", href=True):
        href = a.get("href", "")
        if "/incidents" in href:
            txt = a.get_text(" ", strip=True)
            if re.search(r"\bIncident\s+\d+", txt, flags=re.I):
                incident_link = a
                break
            if not incident_link:
                incident_link = a

    if incident_link:
        href = incident_link["href"]
        url = "https://trustportal.netskope.com" + href if href.startswith("/") else href
        title = incident_link.get_text(" ", strip=True)
    else:
        title = None
        el = container.find(class_=re.compile(r"incident-title|card-title", re.I))
        if el:
            title = el.get_text(strip=True)
        if not title:
            h = container.find(["h1", "h2", "h3", "h4"])
            if h:
                title = h.get_text(strip=True)
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
        if dt:
            parsed_times.append(dt)
    if parsed_times:
        parsed_times.sort()
        started_at = parsed_times[0]
        ended_at = parsed_times[-1]

    # Regex (acepta sin año)
    all_dates = [parse_datetime_any(m.group(0)) for m in re.finditer(DATE_REGEX_LOOSE, text or "", flags=re.I)]
    all_dates = [d for d in all_dates if d]

    # Inicio = tras 'Investigating'/'Identified' ; si no, más antigua
    start_from_label = nearest_date_after_any(["Investigating", "Identified"], text)
    if start_from_label:
        started_at = start_from_label
    elif not started_at and all_dates:
        started_at = min(all_dates)

    # Fin = tras 'Resolved' ; si no, más reciente como último update
    end_from_resolved = nearest_date_after("Resolved", text)
    if end_from_resolved:
        ended_at = end_from_resolved
    elif not ended_at and all_dates:
        ended_at = max(all_dates)

    if not started_at:
        started_at = find_nearest_header_date(container)

    # Estado = último evento del timeline
    status = latest_status_from_text(text) or "Update"

    return {
        "title": title,
        "status": status,
        "url": url,
        "started_at": started_at,
        "ended_at": ended_at,
        "raw_text": text,
    }


def dedup_incidents(items):
    seen = set()
    out = []
    for it in items:
        key = ((it.get("title") or "").strip(), (it.get("url") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


# =========================
# Scrape + clasificación
# =========================
def analizar_netskope(driver):
    print("🔍 Cargando Netskope...")
    driver.get(NETSKOPE_URL)

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(., 'Incidents') or contains(., 'Open Incidents') or contains(., 'Past Incidents')]")
        )
    )

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
                        raise StopIteration  # salir de ambos loops
                    except Exception:
                        pass
    except StopIteration:
        pass
    except Exception:
        pass

    # Espera a que aparezca al menos un enlace de incidente en el DOM
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/incidents/']"))
        )
    except Exception:
        pass

    time.sleep(2)

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
            return True  # la sección ya es "Previous 15 days"
        return dt >= cutoff

    pasados_15 = [i for i in pasados if in_lookback(i)]

    # En activos, descartar cualquier 'Resolved'
    activos = [i for i in activos if (i.get("status") or "").lower() != "resolved"]

    return activos, pasados_15


# =========================
# Entrypoint del vendor
# =========================
def run():
    driver = start_driver()
    try:
        activos, pasados_15 = analizar_netskope(driver)
        resumen = header("Netskope") + "\n" + render_incidents(activos, pasados_15)
        print("\n===== NETSKOPE =====")
        print(resumen)
        print("====================\n")
        send_telegram(resumen)
        send_teams(resumen)
    except Exception as e:
        print(f"[netskope] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"<b>Netskope - Monitor</b>\nSe produjo un error:\n<pre>{str(e)}</pre>")
        send_teams(f"❌ Netskope - Monitor\nSe produjo un error: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
