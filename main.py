import os
import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import requests

# Configuración de variables de entorno (Telegram / Teams)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")

URL_NETSKOPE = "https://trustportal.netskope.com/incidents"

def iniciar_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    return webdriver.Chrome(options=options)

def extraer_incidentes_pasados(driver):
    driver.get(URL_NETSKOPE)
    time.sleep(5)  # Esperar carga JS

    secciones = driver.find_elements(By.XPATH, "//div[contains(@class, 'component') and .//h3[contains(text(), 'Past Incidents')]]")
    incidentes = []

    if not secciones:
        print("No se encontró la sección de incidentes pasados.")
        return []

    for seccion in secciones:
        contenedores = seccion.find_elements(By.XPATH, ".//div[contains(@class, 'status-incidents')]")

        for contenedor in contenedores:
            texto = contenedor.text.strip()
            if not texto:
                continue

            lineas = texto.splitlines()
            fecha = ""
            titulo = ""
            estado = ""

            for linea in lineas:
                if "Incident" in linea:
                    titulo = linea.strip()
                elif any(palabra in linea for palabra in ["Resolved", "Mitigated", "Investigating"]):
                    estado = linea.strip()
                elif "Aug" in linea or "Jul" in linea:  # ajustar si hay meses en español
                    fecha = linea.strip()

            if fecha and titulo:
                try:
                    fecha_dt = datetime.strptime(fecha, "%b %d, %Y")
                    incidentes.append({
                        "fecha": fecha_dt,
                        "titulo": titulo,
                        "estado": estado
                    })
                except Exception as e:
                    print(f"Error al parsear fecha: {fecha} -> {e}")

    return incidentes

def filtrar_incidentes_recientes(incidentes, dias=15):
    hoy = datetime.utcnow()
    limite = hoy - timedelta(days=dias)
    return [i for i in incidentes if i["fecha"] >= limite]

def construir_resumen(incidentes):
    if not incidentes:
        return "✅ No hay incidentes reportados en los últimos 15 días."

    resumen = "📊 *Resumen de incidentes Netskope (últimos 15 días)*\n\n"
    for i in incidentes:
        resumen += f"📅 *{i['fecha'].strftime('%Y-%m-%d')}*\n"
        resumen += f"🔹 *{i['titulo']}*\n"
        resumen += f"📌 Estado: `{i['estado']}`\n\n"
    return resumen

def enviar_telegram(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_USER_ID:
        print("⚠️ Variables TELEGRAM no definidas.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_USER_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        r = requests.post(url, json=data)
        print("✅ Enviado a Telegram:", r.status_code)
    except Exception as e:
        print("❌ Error enviando a Telegram:", e)

def enviar_teams(mensaje):
    if not TEAMS_WEBHOOK_URL:
        print("⚠️ TEAMS_WEBHOOK_URL no definida.")
        return

    data = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": "Resumen Netskope",
        "themeColor": "0078D7",
        "title": "🛡️ Netskope - Resumen de incidentes (últimos 15 días)",
        "text": mensaje.replace("*", "**").replace("`", "")
    }
    try:
        r = requests.post(TEAMS_WEBHOOK_URL, json=data)
        print("✅ Enviado a Teams:", r.status_code)
    except Exception as e:
        print("❌ Error enviando a Teams:", e)

def main():
    print("🔍 Iniciando análisis de Netskope...")
    driver = iniciar_driver()
    incidentes = extraer_incidentes_pasados(driver)
    driver.quit()

    recientes = filtrar_incidentes_recientes(incidentes)
    resumen = construir_resumen(recientes)

    enviar_telegram(resumen)
    enviar_teams(resumen)

if __name__ == "__main__":
    main()
