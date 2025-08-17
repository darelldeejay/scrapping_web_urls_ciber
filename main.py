import os
import requests
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
import time

# Variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")

def iniciar_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-software-rasterizer")

    service = Service("/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Variables de entorno para Telegram no configuradas correctamente.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje
    }

    try:
        response = requests.post(url, data=data)
        print(f"Telegram: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

def enviar_teams(mensaje):
    if not TEAMS_WEBHOOK_URL:
        print("❌ Variable de entorno para Microsoft Teams no configurada.")
        return

    data = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": "Alerta de incidente",
        "themeColor": "0078D7",
        "title": "🔔 Estado de fabricantes",
        "text": mensaje
    }

    try:
        r = requests.post(TEAMS_WEBHOOK_URL, json=data)
        print(f"Teams: {r.status_code}")
    except Exception as e:
        print(f"Error enviando a Teams: {e}")

def analizar_netskope(driver):
    print("🔍 Iniciando análisis de Netskope...")
    url = "https://trustportal.netskope.com/incidents"
    driver.get(url)
    time.sleep(5)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    incidentes = []

    # Buscar bloques de incidentes (todos los bloques de fecha)
    bloques_fecha = soup.find_all("div", class_="col-12")  # cada fecha contiene uno o más incidentes

    hace_15_dias = datetime.utcnow() - timedelta(days=15)

    for bloque in bloques_fecha:
        # Buscar encabezado de fecha
        fecha_encabezado = bloque.find("h5")
        if not fecha_encabezado:
            continue

        try:
            fecha_str = fecha_encabezado.text.strip()
            fecha_dt = datetime.strptime(fecha_str, "%b %d, %Y")
        except:
            continue

        # Verificar si está en los últimos 15 días
        if fecha_dt < hace_15_dias:
            continue

        # Buscar incidentes dentro del bloque
        incidentes_divs = bloque.find_all("div", class_="incident")
        for incidente_div in incidentes_divs:
            titulo = incidente_div.find("div", class_="incident-title")
            estado = incidente_div.find("div", class_="incident-status")
            if titulo and estado:
                incidentes.append(f"• {fecha_dt.strftime('%Y-%m-%d')}: {titulo.text.strip()} - Estado: {estado.text.strip()}")

    if incidentes:
        return "🛠️ Incidentes de Netskope en los últimos 15 días:\n" + "\n".join(incidentes)
    else:
        return "✅ No hay incidentes recientes en Netskope en los últimos 15 días."

def main():
    driver = iniciar_driver()
    resumen = analizar_netskope(driver)
    driver.quit()

    print("Resumen generado:\n", resumen)

    enviar_telegram(resumen)
    enviar_teams(resumen)

if __name__ == "__main__":
    main()
