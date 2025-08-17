# vendors/proofpoint.py
import os
import re
import traceback
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams
from common.format import header, render_incidents

URL = "https://proofpoint.my.site.com/community/s/proofpoint-current-incidents"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# Palabras que podrían aparecer en títulos/estados (por si algún día listan detalles)
STATUS_HINTS = ["Investigating", "Identified", "Monitoring", "Mitigated", "Update", "Degraded", "Resolved"]


def wait_for_page(driver):
    # Espera a que aparezca el heading o el mensaje de "No incidents"
    preds = [
        (By.XPATH, "//*[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'PROOFPOINT CURRENT INCIDENTS')]"),
        (By.XPATH, "//*[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'NO CURRENT IDENTIFIED INCIDENTS')]"),
        (By.CSS_SELECTOR, "main, div, section"),  # fallback
    ]
    for by, sel in preds:
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((by, sel)))
            return
        except Exception:
            continue


def parse_incidents(html: str):
    soup = BeautifulSoup(html, "lxml")

    # 1) Si muestran "No current identified incidents" -> sin incidentes
    no_inc = soup.find(string=re.compile(r"No\s+current\s+identified\s+incidents", re.I))
    if no_inc:
        return [], []  # activos, pasados (Proofpoint no publica pasados en esta URL)

    # 2) Intentar localizar el bloque bajo el heading "PROOFPOINT CURRENT INCIDENTS"
    heading = soup.find(
        lambda tag: tag.name in ["h1", "h2", "h3", "div", "p"]
        and tag.get_text(strip=True)
        and "proofpoint current incidents" in tag.get_text(strip=True).lower()
    )
    container = None
    if heading:
        # Primero intenta dentro del mismo contenedor
        container = heading.parent if heading.parent else heading
        # Si no aparecen enlaces ahí, recorre siblings siguientes
        if not container.select("a[href]"):
            container = heading.find_next("div") or heading

    # 3) Extraer items: esta página normalmente solo lista activos; si alguna vez listan cards,
    # tomamos enlaces/filas visibles dentro del contenedor o, si no, de toda la página.
    anchors = []
    scope = container if container else soup
    anchors = scope.select("a[href]")

    incidents = []
    for a in anchors:
        txt = (a.get_text(" ", strip=True) or "")
        href = a.get("href", "")
        # Filtrar enlaces de navegación obvios
        if not txt or len(txt) < 6:
            continue
        if re.search(r"support\s*case|knowledge|community|login|help", txt, re.I):
            continue
        # Preferimos anchors dentro del bloque principal (evita cabeceras/footers)
        title = txt
        url = href if href.startswith("http") else f"https://proofpoint.my.site.com{href}" if href.startswith("/") else href

        # Heurística muy suave: si el texto contiene una pista de estado, úsala; si no, "Update"
        status = next((s for s in STATUS_HINTS if s.lower() in txt.lower()), "Update")

        incidents.append({
            "title": title,
            "status": status,
            "url": url,
            "started_at": None,  # esta página no publica fechas en la vista simple
            "ended_at": None,
            "raw_text": txt,
        })

    # Si no detectamos items fiables, tratamos como "sin incidentes"
    if not incidents:
        return [], []

    # La URL solo muestra incidentes ACTUALES
    return incidents, []


def run():
    driver = start_driver()
    try:
        driver.get(URL)
        wait_for_page(driver)

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("proofpoint_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML guardado en proofpoint_page_source.html")
            except Exception as e:
                print(f"No se pudo guardar HTML: {e}")

        activos, pasados = parse_incidents(html)

        resumen = header("Proofpoint") + "\n" + render_incidents(activos, pasados)
        print("\n===== PROOFPOINT =====")
        print(resumen)
        print("======================\n")

        send_telegram(resumen)
        send_teams(resumen)

    except Exception as e:
        print(f"[proofpoint] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"<b>Proofpoint - Monitor</b>\nSe produjo un error:\n<pre>{str(e)}</pre>")
        send_teams(f"❌ Proofpoint - Monitor\nSe produjo un error: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
