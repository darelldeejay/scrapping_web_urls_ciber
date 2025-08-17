import os
import sys
import re
import json
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# =========================
# Configuración y constantes
# =========================
NETSKOPE_URL = "https://trustportal.netskope.com/incidents"
LOOKBACK_DAYS = 15
REQUEST_TIMEOUT = 25

# Entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")
CHROME_PATH = os.getenv("CHROME_PATH")  # lo exporta browser-actions/setup-chrome
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"


# =========================
# Notificaciones
# =========================
def enviar_telegram(mensaje: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_BOT_TOKEN/TELEGRAM_USER_ID no configurados. Omitiendo Telegram.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        print(f"Telegram: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")
        traceback.print_exc()


def enviar_teams(mensaje: str) -> None:
    if not TEAMS_WEBHOOK_URL:
        print("❌ TEAMS_WEBHOOK_URL no configurado. Omitiendo Teams.")
        return
    try:
        payload = {"text": mensaje}
        r = requests.post(
            TEAMS_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        print(f"Teams: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"Error enviando a Teams: {e}")
        traceback.print_exc()


# =========================
# Selenium
# =========================
def iniciar_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--disable-software-rasterizer")
    if CHROME_PATH:
        opts.binary_location = CHROME_PATH

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(60)
    driver.implicitly_wait(2)
    return driver


def safe_click(driver: webdriver.Chrome, element) -> bool:
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        element.click()
        return True
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            return False


def expandir_past_incidents(driver: webdriver.Chrome) -> None:
    candidatos = [
        "Past Incidents (Previous 15 days)",
        "Past Incidents",
        "Previous 15 days",
    ]
    for label in candidatos:
        try:
            elems = driver.find_elements(By.XPATH, f"//*[contains(normalize-space(.), '{label}')]")
            for el in elems:
                tag = (el.tag_name or "").lower()
                txt = (el.text or "").strip()
                if not txt:
                    continue
                if tag in ("summary", "button") and safe_click(driver, el):
                    print(f"[Expand] Click en <{tag}> para '{label}'.")
                    time.sleep(1)
                    return
                parent = el
                for _ in range(3):
                    try:
                        parent = parent.find_element(By.XPATH, "./..")
                    except Exception:
                        parent = None
                    if not parent:
                        break
                    aria_expanded = (parent.get_attribute("aria-expanded") or "").lower()
                    role = (parent.get_attribute("role") or "").lower()
                    if aria_expanded in ("false", "true") or role == "button":
                        if safe_click(driver, parent):
                            print(f"[Expand] Click en contenedor colapsable para '{label}'.")
                            time.sleep(1)
                            return
        except Exception:
            continue
    print("[Expand] No fue necesario o no se pudo expandir explícitamente 'Past Incidents'.")


# =========================
# Parsing helpers
# =========================
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic"

# Estricto (con año) — se mantiene por compatibilidad
DATE_REGEX_STRICT = rf"({MONTHS})\s+\d{{1,2}},?\s+\d{{4}}(?:\s+\d{{1,2}}:\d{{2}}\s*(AM|PM)?)?\s*(UTC|GMT|[A-Z]{{2,4}})?"

# Flexible (sin exigir año, con hora opcional) — se usa por defecto
DATE_REGEX_LOOSE = rf"({MONTHS})\s+\d{{1,2}}(?:,\s*\d{{4}})?(?:\s*,?\s*\d{{1,2}}:\d{{2}}\s*(?:AM|PM)?(?:\s*(?:UTC|GMT|[A-Z]{{2,4}}))?)?"

STATUS_TOKENS = ["Resolved", "Mitigated", "Monitoring", "Identified", "Investigating", "Degraded", "Update"]


def parse_datetime_any(text: str):
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


def nearest_date_after(label_text: str, full_text: str):
    """Primera fecha tras la ocurrencia de label_text (p.ej., 'Resolved')."""
    try:
        pos = full_text.lower().find(label_text.lower())
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
    """Devuelve la etiqueta de estado correspondiente al último evento del timeline (lo que aparece primero en el texto)."""
    low = (text or "").lower()
    # Ordenado de más reciente a menos reciente típico en el portal
    candidates = ["update", "mitigated", "monitoring", "identified", "investigating", "degraded", "resolved"]
    positions = []
    for tok in candidates:
        idx = low.find(tok)
        if idx != -1:
            positions.append((idx, tok.title()))
    positions.sort()
    return positions[0][1] if positions else None


def find_nearest_header_date(node):
    """Fecha del encabezado (p.ej. <h5> 'Aug 15, 2025') más cercano por encima."""
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


# =========================
# Normalización de tarjetas
# =========================
def normalize_card(card) -> dict:
    """
    Normaliza una tarjeta de incidente:
    - Título: del <a href="/incidents/..."> cuyo texto contiene "Incident <id>".
    - Fechas: inicio = Investigating/Identified ; fin = Resolved (si existe).
    - Estado: el ÚLTIMO evento del timeline (lo primero que aparece en el bloque).
    """
    container = card
    if getattr(card, "name", None) == "a":
        container = incident_container_for(card)

    # URL y título (preferir enlace principal del incidente)
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

    # Texto completo del contenedor
    text = container.get_text(" ", strip=True) if hasattr(container, "get_text") else ""

    # FECHAS
    started_at = None
    ended_at = None

    # <time> tags
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

    # Si seguimos sin inicio, usa el encabezado de fecha cercano
    if not started_at:
        started_at = find_nearest_header_date(container)

    # ESTADO: último evento del timeline (lo que aparece primero en el bloque)
    status = latest_status_from_text(text)
    if not status:
        status = "Update"

    return {
        "title": title,
        "status": status,
        "url": url,
        "started_at": started_at,
        "ended_at": ended_at,
        "raw_text": text,
    }


def dedup_incidents(items: list[dict]) -> list[dict]:
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
def analizar_netskope(driver: webdriver.Chrome) -> tuple[list[dict], list[dict]]:
    print("🔍 Cargando Netskope...")
    driver.get(NETSKOPE_URL)

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(., 'Incidents') or contains(., 'Open Incidents') or contains(., 'Past Incidents')]")
        )
    )

    expandir_past_incidents(driver)

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
            with open("page_source.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("💾 HTML guardado en page_source.html")
        except Exception as e:
            print(f"No se pudo guardar page_source.html: {e}")

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

    def in_lookback(inc: dict) -> bool:
        dt = inc.get("ended_at") or inc.get("started_at")
        if not dt:
            return True  # la propia sección ya es "Previous 15 days"
        return dt >= cutoff

    pasados_15 = [i for i in pasados if in_lookback(i)]

    # En activos, descartar cualquier 'Resolved'
    activos = [i for i in activos if (i.get("status") or "").lower() != "resolved"]

    return activos, pasados_15


# =========================
# Formato de salida
# =========================
def formatear_resumen(activos: list[dict], pasados: list[dict]) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    partes = [f"<b>Netskope - Estado de Incidentes</b>\n<i>{now}</i>"]

    if activos:
        partes.append("\n<b>Incidentes activos</b>")
        for i, inc in enumerate(activos, 1):
            title = inc.get("title") or "Sin título"
            status = inc.get("status") or "-"
            url = inc.get("url")
            started = inc.get("started_at")
            started_s = started.strftime("%Y-%m-%d %H:%M UTC") if started else "N/D"
            if url:
                partes.append(f"{i}. <b>{status}</b> — <a href=\"{url}\">{title}</a>\n   Inicio: {started_s}")
            else:
                partes.append(f"{i}. <b>{status}</b> — {title}\n   Inicio: {started_s}")
    else:
        partes.append("\n<b>Incidentes activos</b>\n- No hay incidentes activos reportados.")

    if pasados:
        partes.append("\n<b>Incidentes últimos 15 días</b>")
        for i, inc in enumerate(pasados, 1):
            title = inc.get("title") or "Sin título"
            status = inc.get("status") or "-"
            url = inc.get("url")
            started = inc.get("started_at")
            ended = inc.get("ended_at")
            started_s = started.strftime("%Y-%m-%d %H:%M UTC") if started else "N/D"
            ended_s = ended.strftime("%Y-%m-%d %H:%M UTC") if ended else "N/D"
            if url:
                partes.append(f"{i}. <b>{status}</b> — <a href=\"{url}\">{title}</a>\n   Inicio: {started_s} · Fin: {ended_s}")
            else:
                partes.append(f"{i}. <b>{status}</b> — {title}\n   Inicio: {started_s} · Fin: {ended_s}")
    else:
        partes.append("\n<b>Incidentes últimos 15 días</b>\n- No hay incidentes en los últimos 15 días.")

    return "\n".join(partes)


def main() -> int:
    driver = None
    try:
        driver = iniciar_driver()
        activos, pasados_15 = analizar_netskope(driver)
        resumen = formatear_resumen(activos, pasados_15)

        print("\n===== RESUMEN A ENVIAR =====")
        print(resumen)
        print("===== FIN RESUMEN =====\n")

        enviar_telegram(resumen)
        enviar_teams(resumen)
        return 0

    except Exception as e:
        err = f"[ERROR] {e}\n{traceback.format_exc()}"
        print(err)
        enviar_telegram(f"<b>Netskope - Monitor</b>\nSe produjo un error:\n<pre>{str(e)}</pre>")
        enviar_teams(f"❌ Netskope - Monitor\nSe produjo un error: {str(e)}")
        return 1

    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
