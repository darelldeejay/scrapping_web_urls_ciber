# common/notify.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import requests
from datetime import datetime, timezone
from typing import Optional

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

def _is_truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "y", "on")

def _capture_write(channel: str, text: str) -> None:
    """
    Si DIGEST_CAPTURE=1, escribe capturas en DIGEST_OUT_DIR/<vendor>.capture.txt
    """
    if not _is_truthy_env("DIGEST_CAPTURE"):
        return
    out_dir = os.getenv("DIGEST_OUT_DIR", ".github/out/vendors")
    vendor = os.getenv("CURRENT_VENDOR", "unknown")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{vendor}.capture.txt")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n[{ts}] <{channel}>\n{text}\n")

def send_telegram(text: str) -> None:
    _capture_write("telegram", text)
    if _is_truthy_env("NOTIFY_DRY_RUN"):
        return
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_USER_ID")
    if not token or not chat_id:
        # No reventar si falta secret; la captura ya quedó grabada
        return
    url = TELEGRAM_API.format(token=token)
    # Telegram máx ~4096; enviamos tal cual (tus módulos suelen ser compactos)
    r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=30)
    # No lanzamos excepción dura en notificaciones del flujo principal

def send_teams(markdown: str, title: Optional[str] = None) -> None:
    _capture_write("teams", f"{('**'+title+'**\\n\\n') if title else ''}{markdown}")
    if _is_truthy_env("NOTIFY_DRY_RUN"):
        return
    webhook = os.getenv("TEAMS_WEBHOOK_URL")
    if not webhook:
        return
    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title or "Status",
        "themeColor": "2B579A",
        "title": title or "Status",
        "text": markdown,
    }
    try:
        requests.post(webhook, json=card, timeout=30)
    except Exception:
        pass

class Notifier:
    """Compatibilidad con vendors que usan una clase."""
    def telegram(self, text: str) -> None:
        send_telegram(text)
    def teams(self, text: str, title: Optional[str] = None) -> None:
        send_teams(text, title=title)
