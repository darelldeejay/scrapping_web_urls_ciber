import requests
from bs4 import BeautifulSoup
import json
import os

# Variables de entorno
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")

INCIDENTS_FILE = 'incidents.json'
NETSKOPE_URL = 'https://trustportal.netskope.com/incidents'

def obtener_incidentes_netskope():
    response = requests.get(NETSKOPE_URL)
    soup = BeautifulSoup(response.text, 'html.parser')
    incidentes = []
    for card in soup.select('div.card.incident-card'):
        titulo = card.select_one('h3.card-title').text.strip()
        fecha = card.select_one('div.card-subtitle').text.strip()
        incidente_id = f"{fecha} - {titulo}"
        incidentes.append({
            "id": incidente_id,
            "titulo": titulo,
            "fecha": fecha
        })
    return incidentes

def cargar_incidentes_anteriores():
    if os.path.exists(INCIDENTS_FILE):
        with open(INCIDENTS_FILE, 'r') as f:
            return json.load(f)
    return []

def guardar_incidentes(incidentes):
    with open(INCIDENTS_FILE, 'w') as f:
        json.dump(incidentes, f, indent=2)

def enviar_telegram(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_USER_ID:
        print("⚠️ Falta configuración de Telegram")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_USER_ID, "text": mensaje}
    requests.post(url, data=data)

def enviar_teams(mensaje):
    if not TEAMS_WEBHOOK_URL:
        print("⚠️ Falta configuración de Teams")
        return
    data = {"text": mensaje}
    requests.post(TEAMS_WEBHOOK_URL, json=data)

def main():
    incidentes_actuales = obtener_incidentes_netskope()
    incidentes_previos = cargar_incidentes_anteriores()

    nuevos = [i for i in incidentes_actuales if i['id'] not in {x['id'] for x in incidentes_previos}]
    
    if nuevos:
        for inc in nuevos:
            mensaje = f"🚨 *Nuevo incidente en Netskope*\n\n📅 {inc['fecha']}\n📌 {inc['titulo']}\n🔗 {NETSKOPE_URL}"
            print("Enviando alerta:\n", mensaje)
            enviar_telegram(mensaje)
            enviar_teams(mensaje)
        guardar_incidentes(incidentes_actuales)
    else:
        print("✅ Sin nuevos incidentes.")

if __name__ == '__main__':
    main()
