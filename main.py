import os
import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import telegram
import requests

NETSKOPE_URL = "https://trustportal.netskope.com/incidents"

# Función para inicializar Selenium en modo headless
def iniciar_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=chrome_options)

# Función para scrapear incidentes pasados de Netskope
def obtener_incidentes_netskope():
    driver = iniciar_driver()
    driver.get(NETSKOPE_URL)
    time.sleep(3)  # Esperar que se cargue el contenido JS

    incidentes = []
    hoy = datetime.utcnow()
    hace_15_dias = hoy - timedelta(days=15)

    try:
        bloques_fecha = driver.find_elements(By.XPATH, "//h3[contains(text(),'Aug') or contains(text(),'Jul') or contains(text(),'Jun')]")
        for bloque in bloques_fecha:
            fecha_texto = bloque.text.strip()
            try:
                fecha_incidente = datetime.strptime(fecha_texto, "%b %d, %Y")
            except ValueError:
                continue

            if fecha_incidente < hace_15_dias:
                continue

            siguiente = bloque.find_element(By.XPATH, "./following-sibling::*[1]")
            if "Incident" in siguiente.text:
                titulo = siguiente.text.strip()
                detalles = siguiente.find_element(By.XPATH, "./following-sibling::*[1]").text.strip()
                incidentes.append(f"📅 {fecha_texto}\n🧾 {titulo}\n{detalles}\n")
    except Exception as e:
        incidentes.append(f"⚠️ Error analizando la página de Netskope: {e}")
    finally:
        driver.quit()

    return incidentes

# Función para enviar mensaje por Telegram
def enviar_telegram(mensaje):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    user_id = os.getenv("TELEGRAM_USER_ID")
    if token and user_id:
        bot = telegram.Bot(token=token)
        bot.send_message(chat_id=user_id, text=mensaje)
    else:
        print("⚠️ Token o User ID de Telegram no configurado")

# Función para enviar mensaje por Teams
def enviar_teams(mensaje):
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    if webhook_url:
        json_data = { "text": mensaje }
        try:
            requests.post(webhook_url, json=json_data)
        except Exception as e:
            print(f"Error enviando a Teams: {e}")
    else:
        print("ℹ️ Webhook de Teams no configurado")

# Ejecutar todo
def main():
    resumen = "📊 *Resumen de incidentes Netskope (últimos 15 días)*\n\n"
    incidentes = obtener_incidentes_netskope()

    if incidentes:
        resumen += "\n".join(incidentes)
    else:
        resumen += "✅ No hay incidentes reportados en los últimos 15 días."

    print(resumen)
    enviar_telegram(resumen)
    enviar_teams(resumen)

if __name__ == "__main__":
    main()
