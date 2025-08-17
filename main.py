import requests
from bs4 import BeautifulSoup
import os
import hashlib

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")

NETSKOPE_URL = 'https://trustportal.netskope.com/incidents'
HASH_FILE = 'last_summary_hash.txt'

# Diccionario de traducción de estados
TRADUCCION_ESTADOS = {
    "Resolved": "Resuelto",
    "Mitigated": "Mitigado",
    "Update": "Actualización",
    "Investigating": "Investigando",
    "Monitoring": "Monitorizando",
    "Identified": "Identificado",
    "In Progress": "En progreso",
    "Desconocido": "Desconocido"
}

def traducir_estado(estado_original):
    return TRADUCCION_ESTADOS.get(estado_original, estado_original)

def obtener_incidentes_netskope():
    response = requests.get(NETSKOPE_URL)
    soup = BeautifulSoup(response.text, 'html.parser')

    incidentes = []
    cards = soup.select('div.card.incident-card')
    
    for card in cards:
        titulo = card.select_one('h3.card-title')
        fecha = card.select_one('div.card-subtitle')
        estado = card.select_one('div.card-status span')

        if titulo:
            estado_texto = estado.text.strip() if estado else "Desconocido"
            incidente = {
                "titulo": titulo.text.strip(),
                "fecha": fecha.text.strip() if fecha else "Sin fecha",
                "estado": traducir_estado(estado_texto)
            }
            incidentes.append(incidente)

    return incidentes

def generar_resumen(incidentes):
    if not incidentes:
        return "✅ No hay incidentes reportados por Netskope en los últimos 15 días."

    resumen = f"📊 *Resumen de incidentes Netskope (últimos 15 días)*\n\n"
    for i, inc in enumerate(incidentes, 1):
        resumen += f"{i}. *{inc['titulo']}*\n"
        resumen += f"   📅 Fecha: {inc['fecha']}\n"
        resumen += f"   🔄 Estado: `{inc['estado']}`\n\n"
    resumen += f"🔗 Ver más: {NETSKOPE_URL}"
    return resumen

def calcular_hash(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()

def cargar_hash_anterior():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, 'r') as f:
            return f.read().strip()
    return ""

def guardar_hash_actual(hash_texto):
    with open(HASH_FILE, 'w') as f:
        f.write(hash_texto)

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
    requests.post(url, data=data)

def enviar_teams(mensaje):
    if not TEAMS_WEBHOOK_URL:
        print("⚠️ Falta configuración de Teams")
        return
    data = {"text": mensaje}
    requests.post(TEAMS_WEBHOOK_URL, json=data)

def main():
    incidentes = obtener_incidentes_netskope()
    resumen = generar_resumen(incidentes)

    hash_actual = calcular_hash(resumen)
    hash_anterior = cargar_hash_anterior()

    if hash_actual == hash_anterior:
        print("✅ No hay cambios en los incidentes. No se envía alerta.")
        return

    print("📤 Enviando resumen actualizado...")
    enviar_telegram(resumen)
    enviar_teams(resumen)
    guardar_hash_actual(hash_actual)

if __name__ == '__main__':
    main()
