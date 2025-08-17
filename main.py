import os
import requests

# Leer variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_mensaje_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Variables de entorno para Telegram no configuradas.")
        print(f"TELEGRAM_TOKEN: {TELEGRAM_TOKEN}")
        print(f"TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje
    }

    try:
        response = requests.post(url, json=data)
        print(f"✅ Respuesta Telegram: {response.status_code}")
        print(response.text)
    except Exception as e:
        print("❌ Error enviando a Telegram:", str(e))

# Prueba
print("🔍 Enviando mensaje de prueba a Telegram...")
enviar_mensaje_telegram("🔔 Prueba de notificación desde script de test")
