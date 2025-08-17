import requests
from bs4 import BeautifulSoup
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")

NETSKOPE_URL = 'https://trustportal.netskope.com/incidents'

def obtener_incidentes_netskope():
    response = requests.get(NETSKOPE_URL)
    soup = BeautifulSoup(response.text, 'html.parser')

    incidentes = []
    cards = soup.select('div.card.incident-card')
    for card in cards:
        titulo = card.select_one('h3.card-title')
        fecha = card.select_one('div.card-subtitle')
        status_div = card.select_one('div.card-status span')
        
        if titulo and fecha:
            incidente = {
                "titulo": titulo.text.strip(),
                "fecha": fecha.text.strip(),
                "estado": status_div.text.strip() if status_div else "Unknown"
            }
            incidentes.append(incidente)
    return incidentes

def generar_resumen(incidentes):
    if not incidentes:
        return "✅ No hay incidentes reportados en Netskope en los últimos 15 días."

    resumen = f"📊 *Resumen de incidentes Netskope (últimos 15 días)*\n\n"
    for i, inc in enumerate(incidentes, 1):
        resumen += f"{i}. *{inc['titulo']}*\n"
        resumen += f"   📅 Fecha: {inc['fecha']}\n"
        resumen += f"   🔄 Estado: `{inc['estado']}`\n\n"
    resumen += f"🔗 Ver más: {NETSKOPE_URL}"
    return resumen

def enviar_telegram(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_USER_ID:
        print("⚠️ Falta configuración de Telegram")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_USER_ID,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    r = requests.post(url, data=data)
    print("Telegram:", r.text)

def enviar_teams(mensaje):
    if not TEAMS_WEBHOOK_URL:
        print("⚠️ Falta configuración de Teams")
        return
    data = {"text": mensaje}
    r = requests.post(TEAMS_WEBHOOK_URL, json=data)
    print("Teams:", r.text)

def main():
    incidentes = obtener_incidentes_netskope()
    resumen = generar_resumen(incidentes)

    enviar_telegram(resumen)
    enviar_teams(resumen)

if __name__ == '__main__':
    main()
