import requests
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID = os.environ.get("TELEGRAM_USER_ID")

def enviar_telegram(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_USER_ID:
        print("⚠️ Falta configuración de Telegram")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_USER_ID, "text": mensaje}
    r = requests.post(url, data=data)
    print("Respuesta de Telegram:", r.text)

def main():
    enviar_telegram("🔔 Prueba desde GitHub Actions (función de Telegram)")

if __name__ == '__main__':
    main()
