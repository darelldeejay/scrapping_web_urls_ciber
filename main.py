import os
import time
from datetime import datetime, timedelta
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# Obtener las variables de entorno reales
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")

URL_NETSKOPE = "https://trust.netskope.com/"

def iniciar_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=chrome_options)

def obtener_incidentes_netskope(driver):
    driver.get(URL_NETSKOPE)
    time.sleep(2)

    try:
        incidents_tab = driver.find_element(By.LINK_TEXT, "Incidents")
        incidents_tab.click()
        time.sleep(2)
    except Exception as e:
        print("No se pudo acceder a la pestaña Incidents:", e)
        return []

    incidentes = []

    try:
        cards = driver.find_elements(By.CLASS_NAME, "card")  # contenedor de incidentes pasados
        for card in cards:
            try:
                date_elem = card.find_element(By.TAG_NAME, "h4")
                fecha_texto = date_elem.text.strip()
                fecha = datetime.strptime(fecha_texto, "%b %d, %Y")

                if fecha >= datetime.utcnow() - timedelta(days=15):
                    titulo_elem = card.find_element(By.CSS_SELECTOR, "strong")
                    estado_elem = card.find_element(By.CLASS_NAME, "status")
                    detalle_elem = card.find_element(By.TAG_NAME, "p")

                    incidentes.append({
                        "fecha": fecha.strftime("%Y-%m-%d"),
                        "titulo": titulo_elem.text.strip(),
                        "estado": estado_elem.text.strip(),
                        "detalle": detalle_elem.text.strip()
                    })
            except Exception as e:
                continue
    except Exception as e:
        print("No se pudieron obtener los incidentes:", e)

    return incidentes

def enviar_telegram(resumen):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_BOT_TOKEN o TELEGRAM_USER_ID no configurados.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": resumen,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=data)
        print("Telegram:", r.text)
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)

def enviar_teams(resumen):
    if not TEAMS_WEBHOOK_URL:
        print("🛑 Webhook de Teams no configurado.")
        return
    data = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": "Resumen de incidentes Netskope",
        "themeColor": "0076D7",
        "title": "📊 <b>Resumen de incidentes Netskope</b> (últimos 15 días)",
        "text": resumen.replace("\n", "<br>")
    }
    try:
        r = requests.post(TEAMS_WEBHOOK_URL, json=data)
        print("Teams:", r.text)
    except Exception as e:
        print("Error enviando mensaje a Teams:", e)

def formatear_resumen(incidentes):
    if not incidentes:
        return "✅ <i>No hay incidentes reportados en los últimos 15 días.</i>"
    resumen = "🚨 <b>Incidentes detectados en Netskope:</b>\n\n"
    for inc in incidentes:
        resumen += f"📅 <b>{inc['fecha']}</b>\n"
        resumen += f"🧾 <b>{inc['titulo']}</b>\n"
        resumen += f"📌 Estado: {inc['estado']}\n"
        resumen += f"🔎 {inc['detalle']}\n\n"
    return resumen

def main():
    print("🔍 Iniciando análisis de Netskope...")
    driver = iniciar_driver()
    incidentes = obtener_incidentes_netskope(driver)
    driver.quit()

    resumen = formatear_resumen(incidentes)

    enviar_telegram(resumen)
    enviar_teams(resumen)

if __name__ == "__main__":
    main()
