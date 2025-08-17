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
# Parsing
# =========================
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic"
DATE_REGEX = rf"({MONTHS})\s+\d{{1,2}},?\s+\d{{4}}(?:\s+\d{{1,2}}:\d{{2}}\s*(AM|PM)?)?\s*(UTC|GMT|[A-Z]{{2,4}})?"
STATUS_TOKENS = ["Resolved", "Mitigated", "Monitoring", "Identified", "Investigating", "Update", "Degraded"]


def parse_datetime_any(text: str):
    try:
        dt = dateparser.parse(text, fuzzy=True)
        if dt:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    m = re.search(DATE_REGEX, text or "", flags=re.I)
    if m:
        try:
            dt = dateparser.parse(m.group(0))
            if dt:
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
        except Exception:
            return None
    return None


def find_section_container(soup: BeautifulSoup, keywords: list[str]):
    """
    Devuelve el contenedor de la sección cuyo heading contiene alguna de las keywords.
    Sin fallback global: si no hay heading, devuelve None.
    """
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
    if not cards:
        nxt = container.find_next_sibling()
        if nxt:
            cards = nxt.select(".incident, [class*='incident'], a[href*='/incidents/']")
    return cards


def extract_sections_strict(soup: BeautifulSoup):
    """
    Devuelve (cards_open, cards_past) separando con precisión según los headings.
    - Open Incidents: estricto (si no hay, lista vacía).
    - Past Incidents: busca su contenedor; si no encuentra, intenta un fallback suave.
    """
    open_container = find_section_container(soup, ["Open Incidents", "Active Incidents", "Active", "Current incidents"])
    past_container = find_section_container(soup, ["Past Incidents (Previous 15 days)", "Past Incidents", "Previous 15 days"])

    open_cards = cards_in_container(open_container) if open_container else []
    past_cards = cards_in_container(past_container)

    # Si no encontró contenedor de past, último recurso: cualquier card bajo un heading que contenga "Past"
    if not past_cards:
        alt_heading = soup.find(lambda tag: tag.name in ["h1","h2","h3","h4","div","summary"]
                                and "past" in tag.get_text(strip=True).lower())
        if alt_heading:
            past_cards = cards_in_container(alt_heading.find_next_sibling())

    return open_cards, past_cards


def nearest_date_after(label_text: str, full_text: str):
    """
    Busca la primera fecha después de la ocurrencia de label_text (p.ej. 'Resolved').
    """
    try:
        pos = full_text.lower().find(label_text.lower())
        if pos == -1:
            return None
        window = full_text[pos: pos + 400]  # ventana razonable
        m = re.search(DATE_REGEX, window, flags=re.I)
        if m:
            return parse_datetime_any(m.group(0))
    except Exception:
        pass
    return None


def normalize_card(card) -> dict:
    """
    Convierte un nodo de incidente a dict estándar.
    Reglas clave:
    - Si aparece 'Resolved' en la cronología, status='Resolved' y ended_at=fecha cercana a 'Resolved'.
    - started_at: intenta primera fecha del bloque; si no, cualquiera encontrada.
    """
    text = card.get_text(separator=" ", strip=True)
    url = None
    a = card.find("a", href=True)
    if a and "/incidents" in a["href"]:
        url = a["href"]
        if url.startswith("/"):
            url = "https://trustportal.netskope.com" + url

    # Título
    title = None
    for cls in ["incident-title", "title", "card-title"]:
        el = card.find(class_=re.compile(cls, re.I))
        if el:
            title = el.get_text(strip=True)
            break
    if not title:
        h = card.find(["h1", "h2", "h3", "h4"])
        if h:
            title = h.get_text(strip=True)
    if not title:
        title = " ".join((text or "").split()[:14]) or "Netskope Incident"

    # Fechas del contenido
    started_at = None
    ended_at = None

    # 1) <time> tags (si existen)
    times = card.find_all("time")
    parsed_times = []
    for t in times:
        dt = parse_datetime_any(t.get("datetime") or t.get_text(strip=True))
        if dt:
            parsed_times.append(dt)

    if parsed_times:
        parsed_times.sort()
        started_at = parsed_times[0]
        ended_at = parsed_times[-1]

    # 2) Regex en texto completo
    if not started_at or not ended_at:
        all_dates = [parse_datetime_any(m.group(0)) for m in re.finditer(DATE_REGEX, text or "", flags=re.I)]
        all_dates = [d for d in all_dates if d]
        if all_dates and not started_at:
            started_at = min(all_dates)
        if all_dates and not ended_at:
            ended_at = max(all_dates)

    # 3) Si hay 'Resolved', priorizar su fecha como ended_at
    status = None
    if "resolved" in (text or "").lower():
        status = "Resolved"
        resolved_dt = nearest_date_after("Resolved", text)
        if resolved_dt:
            ended_at = resolved_dt

    # Si aún no hay status, toma el primer token de estado que aparezca en el texto (orden de prioridad)
    if not status:
        for tok in STATUS_TOKENS:
            if tok.lower() in (text or "").lower():
                status = tok
                # si es 'Update', intenta al menos asignar fecha más reciente como ended_at
                break
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


def analizar_netskope(driver: webdriver.Chrome) -> tuple[list[dict], list[dict]]:
    print("🔍 Cargando Netskope...")
    driver.get(NETSKOPE_URL)

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(., 'Incidents') or contains(., 'Open Incidents') or contains(., 'Past Incidents')]")
        )
    )

    expandir_past_incidents(driver)
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

    # Separa con precisión por secciones
    open_cards, past_cards = extract_sections_strict(soup)

    # Normaliza
    activos = [normalize_card(c) for c in open_cards]
    pasados = [normalize_card(c) for c in past_cards]

    # Dedup dentro de cada sección
    activos = dedup_incidents(activos)
    pasados = dedup_incidents(pasados)

    # Filtra 'pasados' a ventana de 15 días
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)

    def in_lookback(inc: dict) -> bool:
        dt = inc.get("ended_at") or inc.get("started_at")
        if not dt:
            return True  # la propia sección ya es "Previous 15 days"
        return dt >= cutoff

    pasados_15 = [i for i in pasados if in_lookback(i)]

    # IMPORTANTE: no marcar como activos los que estén Resolved
    activos = [i for i in activos if (i.get("status") or "").lower() != "resolved"]

    return activos, pasados_15


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
