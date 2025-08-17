import os

def main():
    print("🔍 Enviando mensaje de prueba a Telegram...")

    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("❌ Variables de entorno para Telegram no configuradas.")
        print(f"TELEGRAM_TOKEN: {token}")
        print(f"TELEGRAM_CHAT_ID: {chat_id}")
        return

    print("✅ Variables cargadas correctamente.")
    print(f"TELEGRAM_TOKEN: {token}")
    print(f"TELEGRAM_CHAT_ID: {chat_id}")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": "✅ Mensaje de prueba desde GitHub Actions"}
    
    try:
        import requests
        response = requests.post(url, data=data)
        print("Telegram:", response.status_code, response.text)
    except Exception as e:
        print("❌ Error al enviar mensaje:", str(e))

if __name__ == "__main__":
    main()
