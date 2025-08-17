import os
import requests
import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
import time

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Variables de entorno para Telegram no configuradas correctamente.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML"
    }
    response = requests.post(url, json=payload)
    print("Telegram:", response.text)

def enviar_teams(mensaje):
    if not TEAMS_WEBHOOK_URL:
        print("❌ Variable de entorno TEAMS_WEBHOOK_URL no configurada.")
        return
    data = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": "Estado de Netskope",
        "themeColor": "0076D7",
        "title": "Actualización de estado de Netskope",
        "text": mensaje
    }
    r = requests.post(TEAMS_WEBHOOK_URL, json=data)
    print("Teams:", r.text)

def iniciar_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.binary_location = "/usr/bin/chromium-browser"

    service = Service("/usr/local/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)

def analizar_netskope():
    print("🔍 Iniciando análisis de Netskope...")
    driver = iniciar_driver()
    url = "https://trustportal.netskope.com/incidents"
    driver.get(url)
    time.sleep(5)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    incidents = soup.select("div.incident-item")
    if not incidents:
        return "✅ No hay incidentes activos de Netskope."

    resumen = "🛑 <b>Incidentes recientes de Netskope (últimos 15 días):</b>\n\n"
    ahora = datetime.datetime.utcnow()

    for incident in incidents:
        fecha_texto = incident.select_one("span.date").text.strip()
        titulo = incident.select_one("div.title").text.strip()
        estado = incident.select_one("span.status").text.strip()

        try:
            fecha = datetime.datetime.strptime(fecha_texto, "%b %d, %Y")
        except ValueError:
            continue

        if (ahora - fecha).days <= 15:
            resumen += f"• <b>{titulo}</b>\n📅 {fecha.strftime('%Y-%m-%d')}\n📌 Estado: {estado}\n\n"

    if resumen.strip().endswith(":</b>"):
        return "✅ No hay incidentes recientes en Netskope."

    return resumen

def main():
    resumen = analizar_netskope()
    if resumen:
        enviar_telegram(resumen)
        enviar_teams(resumen)
    else:
        print("✅ Sin novedades que reportar.")

if __name__ == "__main__":
    main()
