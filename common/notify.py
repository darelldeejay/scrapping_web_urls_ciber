# common/notify.py
import os, json, requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_USER_ID")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL")
REQUEST_TIMEOUT = 25

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram no configurado, omito.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    print(f"Telegram: {r.status_code}")

def send_teams(text: str):
    if not TEAMS_WEBHOOK_URL:
        print("Teams no configurado, omito.")
        return
    payload = {"text": text}
    r = requests.post(TEAMS_WEBHOOK_URL, data=json.dumps(payload),
                      headers={"Content-Type":"application/json"}, timeout=REQUEST_TIMEOUT)
    print(f"Teams: {r.status_code}")
