import os
import requests

def enviar_telegram(mensaje):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("❌ Variables de entorno para Telegram no configuradas correctamente.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": mensaje,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, data=data)
        if response.status_code != 200:
            print(f"⚠️ Telegram: {response.text}")
        else:
            print("✅ Mensaje enviado a Telegram.")
    except Exception as e:
        print(f"❌ Error al enviar a Telegram: {e}")

def enviar_teams(mensaje):
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL")

    if not webhook_url:
        print("❌ Variable de entorno TEAMS_WEBHOOK_URL no configurada.")
        return

    data = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": "Alerta de incidentes",
        "themeColor": "0076D7",
        "title": "🔔 Estado de servicios",
        "text": mensaje
    }

    try:
        response = requests.post(webhook_url, json=data)
        if response.status_code != 200:
            print(f"⚠️ Teams: {response.text}")
        else:
            print("✅ Mensaje enviado a Teams.")
    except Exception as e:
        print(f"❌ Error al enviar a Teams: {e}")

def main():
    print("🔍 Iniciando análisis de Netskope...")

    resumen = "✅ Ejemplo de mensaje de prueba desde el bot."

    # Enviar notificaciones
    enviar_telegram(resumen)
    enviar_teams(resumen)

if __name__ == "__main__":
    main()
