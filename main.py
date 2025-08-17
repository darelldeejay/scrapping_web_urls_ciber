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
LOOKBACK_DAYS = 15  # Ventana de 15 días
REQUEST_TIMEOUT = 25

# Variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")
CHROME_PATH = os.getenv("CHROME_PATH")  # seteado por browser-actions/setup-chrome

# Habilitar guardado de HTML para depuración (opcional: exporta SAVE_HTML=1)
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"


# =========================
# Utilidades de notificación
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
# Selenium (Chrome headless)
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

    # webdriver-manager descarga un ChromeDriver compatible con la versión instalada
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
    """
    Intenta expandir 'Past Incidents (Previous 15 days)' si está colapsada.
    Soporta <summary>, botones de acordeón, encabezados clicables, etc.
    """
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

                # Click directo sobre summary o button
                if tag in ("summary", "button") and safe_click(driver, el):
                    print(f"[Expand] Click en <{tag}> para '{label}'.")
                    time.sleep(1)
                    return

                # Si es un heading, intenta el contenedor con aria-expanded/role=button
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
# Parsing y normalización
# =========================
MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Feb|Mar|Abr|May|Jun|Jul|Ago|Sep|Oct|Nov|Dic"
DATE_REGEX = rf"({MONTHS})\s+\d{{1,2}},?\s+\d{{4}}(?:\s+\d{{1,2}}:\d{{2}}(?:\s*(AM|PM))?\s*(UTC|GMT|[A-Z]{{2,4}})?)?"

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


def incident_status_from_text(text: str) -> str:
    t = (text or "").lower()
    if "resolved" in t or "restored" in t or "completed" in t:
        return "Resolved"
    if "monitoring" in t:
        return "Monitoring"
    if "identified" in t:
        return "Identified"
    if "investigating" in t:
        return "Investigating"
    if "degraded" in t:
        return "Degraded"
    return "Update"


def extract_section_cards(soup: BeautifulSoup, keywords: list[str]):
    """
    Encuentra tarjetas de incidentes bajo una sección cuyo heading contenga cualquiera de `keywords`.
    Devuelve una lista de nodos BeautifulSoup que representan "cards" de incidentes.
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
        # Fallback global
        return soup.select(".incident, [class*='incident'], a[href*='/incidents/']")

    # Intenta localizar un contenedor cercano con los items
    container = heading.find_next_sibling()
    if not container:
        container = heading.parent

    cards = container.select(".incident, [class*='incident'], a[href*='/incidents/']")
    if not cards:
        nxt = container.find_next_sibling()
        if nxt:
            cards = nxt.select(".incident, [class*='incident'], a[href*='/incidents/']")
    if not cards:
        cards = soup.select(".incident, [class*='incident'], a[href*='/incidents/']")
    return cards


def normalize_card(card) -> dict:
    """
    Convierte un nodo de incidente a dict estándar.
    Campos: title, status, url, started_at, ended_at, raw_text
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

    # Fechas (<time> primero)
    started_at = None
    ended_at = None
    times = card.find_all("time")
    if times:
        try:
            t0 = times[0].get("datetime") or times[0].get_text(strip=True)
            started_at = parse_datetime_any(t0)
        except Exception:
            pass
        if len(times) > 1:
            try:
                tn = times[-1].get("datetime") or times[-1].get_text(strip=True)
                ended_at = parse_datetime_any(tn)
            except Exception:
                pass

    # Si no hay <time>, intenta parsear del texto
    if not started_at:
        started_at = parse_datetime_any(text)
    # Si el texto insinúa "Resolved", intenta la última fecha como ended_at
    if not ended_at and ("resolved" in (text or "").lower() or "restored" in (text or "").lower()):
        dates = list(re.finditer(DATE_REGEX, text or "", flags=re.I))
        if dates:
            ended_at = parse_datetime_any(dates[-1].group(0))

    status = incident_status_from_text(text)

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
        key = ((it.get("title") or "").strip(), (it.get("status") or "").strip(), (it.get("url") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def analizar_netskope(driver: webdriver.Chrome) -> tuple[list[dict], list[dict]]:
    print("🔍 Cargando Netskope...")
    driver.get(NETSKOPE_URL)

    # Espera a que la página renderice contenido relacionado
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(., 'Incidents') or contains(., 'Past Incidents') or contains(@class,'incident')]")
        )
    )

    # Intenta expandir la sección de "Past Incidents"
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

    # Sección de incidentes activos
    activos_cards = extract_section_cards(
        soup, ["Active Incidents", "Active incidents", "Active", "Current incidents"]
    )
    activos = [normalize_card(c) for c in activos_cards]
    activos = dedup_incidents(activos)

    # Sección de últimos 15 días (Past Incidents)
    pasados_cards = extract_section_cards(
        soup, ["Past Incidents (Previous 15 days)", "Past Incidents", "Previous 15 days"]
    )
    pasados = [normalize_card(c) for c in pasados_cards]
    pasados = dedup_incidents(pasados)

    # Filtrado por ventana temporal para "pasados"
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)

    def in_lookback(inc: dict) -> bool:
        dt = inc.get("ended_at") or inc.get("started_at")
        if not dt:
            # Si no hay fecha, mantenemos por prudencia (la sección ya es "past 15 days")
            return True
        return dt >= cutoff

    pasados_15 = [i for i in pasados if in_lookback(i)]

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

        # Notificar SIEMPRE (aunque no haya incidentes)
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
