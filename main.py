import os
import requests
import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service

# Función para iniciar el navegador con Selenium
def iniciar_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.binary_location = "/usr/bin/chromium-browser"
    service = Service("/usr/local/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)

# Extrae incidentes desde el sitio Netskope
def obtener_incidentes(driver):
    url = "https://www.netskope.com/company/network-status"
    driver.get(url)
    time.sleep(5)  # esperar carga completa

    incidentes = []
    contenedores = driver.find_elements(By.CSS_SELECTOR, ".incident-container")

    for cont in contenedores:
        try:
            fecha_raw = cont.find_element(By.CSS_SELECTOR, ".incident-date").text.strip()
            resumen = cont.find_element(By.CSS_SELECTOR, ".incident-summary").text.strip()
            estado = cont.find_element(By.CSS_SELECTOR, ".incident-status").text.strip()

            # Parsear fecha con formato correcto
            fecha = datetime.strptime(fecha_raw, "%B %d, %Y")

            if fecha >= datetime.now() - timedelta(days=15):
                incidentes.append(f"📅 {fecha.strftime('%Y-%m-%d')} | {estado} | {resumen}")
        except Exception as e:
            print(f"Error al procesar incidente: {e}")

    return incidentes

# Enviar resumen a Telegram
def enviar_telegram(mensaje):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("❌ Variables de entorno TELEGRAM_TOKEN o TELEGRAM_CHAT_ID no definidas.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": mensaje}

    r = requests.post(url, json=payload)
    print("Telegram:", r.text)

# Enviar resumen a Teams
def enviar_teams(mensaje):
    webhook = os.getenv("TEAMS_WEBHOOK_URL")
    if not webhook:
        print("❌ Variable de entorno TEAMS_WEBHOOK_URL no definida.")
        return

    data = {"text": mensaje}
    r = requests.post(webhook, json=data)
    print("Teams:", r.text)

# Función principal
def main():
    print("🔍 Iniciando análisis de Netskope...")
    driver = iniciar_driver()
    incidentes = obtener_incidentes(driver)
    driver.quit()

    if incidentes:
        resumen = "🚨 Incidentes detectados en Netskope en los últimos 15 días:\n" + "\n".join(incidentes)
    else:
        resumen = "✅ No se han detectado incidentes en Netskope en los últimos 15 días."

    print(resumen)
    enviar_telegram(resumen)
    enviar_teams(resumen)

if __name__ == "__main__":
    main()
