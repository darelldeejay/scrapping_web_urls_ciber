# vendors/proofpoint.py
import os
import re
import traceback
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams
from common.format import header, render_incidents

URL = "https://proofpoint.my.site.com/community/s/proofpoint-current-incidents"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"


def wait_for_page(driver):
    # Espera a que cargue el encabezado o el mensaje de "No incidents"
    preds = [
        (By.XPATH, "//*[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'PROOFPOINT CURRENT INCIDENTS')]"),
        (By.XPATH, "//*[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'NO CURRENT IDENTIFIED INCIDENTS')]"),
    ]
    for by, sel in preds:
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((by, sel)))
            return
        except Exception:
            continue
    # Fallback genérico
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))


def page_text(soup: BeautifulSoup) -> str:
    return " ".join([s.strip() for s in soup.stripped_strings]).lower()


def parse_incidents(html: str):
    soup = BeautifulSoup(html, "lxml")
    txt = page_text(soup)

    # Caso simple (y habitual): mensaje de "no incidents"
    if "no current identified incidents" in txt:
        return [], []

    # Si algún día listan incidentes, solo aceptamos entradas que contengan "Incident ####"
    # para evitar falsos positivos con enlaces de navegación.
    incident_nodes = soup.find_all(string=re.compile(r"\bIncident\s+\d+", re.I))
    incidents = []
    for s in incident_nodes:
        container = s.parent
        # Intenta encontrar el <a> más cercano con href (detalle del incidente)
        a = container.find("a", href=True) if hasattr(container, "find") else None
        url = None
        title = s.strip()
        if a and "/community" not in a.get("href", ""):
            href = a["href"]
            url = href if href.startswith("http") else f"https://proofpoint.my.site.com{href}" if href.startswith("/") else href
            if a.get_text(strip=True):
                title = a.get_text(strip=True)

        incidents.append({
            "title": title,
            "status": "Update",
            "url": url,
            "started_at": None,
            "ended_at": None,
            "raw_text": s,
        })

    # Si no identificamos ninguna entrada válida, considera que no hay incidentes
    if not incidents:
        return [], []

    # Esta URL solo publica incidentes actuales
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
