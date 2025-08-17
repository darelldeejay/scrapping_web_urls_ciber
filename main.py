import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import requests


TELEGRAM_TOKEN = "TU_TOKEN"
TELEGRAM_CHAT_ID = "TU_CHAT_ID"
TEAMS_WEBHOOK_URL = "TU_WEBHOOK"  # O déjalo vacío si no usas Teams

URL_NETSKOPE = "https://trust.netskope.com/"

def iniciar_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.binary_location = "/snap/bin/chromium"
    return webdriver.Chrome(options=options)

def analizar_netskope(driver):
    print("🔍 Iniciando análisis de Netskope...")
    driver.get(URL_NETSKOPE)
    time.sleep(3)

    # Navegar a "Incidents"
    incidents_tab = driver.find_element(By.LINK_TEXT, "Incidents")
    incidents_tab.click()
    time.sleep(3)

    # Buscar secciones de incidentes pasados
    incidentes = driver.find_elements(By.CSS_SELECTOR, ".past-incidents .incidents-list > div")

    resumen = "📊 *Resumen de incidentes Netskope (últimos 15 días)*\n"
    if not incidentes:
        resumen += "✅ No hay incidentes reportados en los últimos 15 días."
        print(resumen)
        return resumen

    encontrados = False
    for incidente in incidentes:
        try:
            fecha_texto = incidente.find_element(By.CSS_SELECTOR, "div:nth-child(1)").text.strip()
            fecha_incidente = datetime.strptime(fecha_texto, "%b %d, %Y")

            if fecha_incidente >= datetime.utcnow() - timedelta(days=15):
                titulo = incidente.find_element(By.CSS_SELECTOR, ".incident-title").text.strip()
                estado = incidente.find_element(By.CSS_SELECTOR, ".incident-status").text.strip()
                resumen += f"\n🛑 *{titulo}*\n📅 Fecha: {fecha_texto}\n🔁 Estado: {estado}\n"
                encontrados = True
        except Exception:
            continue

    if not encontrados:
        resumen += "✅ No hay incidentes reportados en los últimos 15 días."
    print(resumen)
    return resumen

def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=data)
    print("Telegram:", response.text)

def enviar_teams(mensaje):
    if not TEAMS_WEBHOOK_URL.strip():
        return
    data = {"text": mensaje}
    r = requests.post(TEAMS_WEBHOOK_URL, json=data)
    print("Teams:", r.status_code)

def main():
    driver = iniciar_driver()
    resumen = analizar_netskope(driver)
    driver.quit()
    enviar_telegram(resumen)
    enviar_teams(resumen)

if __name__ == "__main__":
    main()
