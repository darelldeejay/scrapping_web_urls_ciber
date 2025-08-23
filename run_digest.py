#!/usr/bin/env python3
import os
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, Optional, List

import requests

from common.templates import (
    load_text_template, load_html_template, render_placeholders,
    wrap_codeblock, chunk_text
)

# ==== Envío ====

def env_or_raise(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return val

def send_telegram(markdown: str, subject: Optional[str] = None) -> None:
    token = env_or_raise("TELEGRAM_BOT_TOKEN")
    chat_id = env_or_raise("TELEGRAM_USER_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Telegram: 4096 máx, usamos ~3900 por seguridad
    for i, chunk in enumerate(chunk_text(markdown, limit=3900), start=1):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            # sin parse_mode -> trata ``` como texto literal y respeta el bloque
        }
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            msg = r.text
            # truncamos error largo
            if len(msg) > 600:
                msg = msg[:600] + "...(truncado)"
            raise RuntimeError(f"Telegram error ({r.status_code}): {msg}")

def send_teams(markdown: str, subject: Optional[str] = None) -> None:
    webhook = env_or_raise("TEAMS_WEBHOOK_URL")
    title = subject or "DORA Daily Digest"
    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": "2B579A",
        "title": title,
        "text": markdown
    }
    r = requests.post(webhook, json=card, timeout=30)
    if r.status_code >= 300:
        msg = r.text
        if len(msg) > 600:
            msg = msg[:600] + "...(truncado)"
        raise RuntimeError(f"Teams webhook error ({r.status_code}): {msg}")

# ==== Carga de datos ====

def load_data(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # fuerza str en todos los valores
    return {k: ("" if v is None else str(v)) for k, v in data.items()}

def inject_defaults(data: Dict[str, str]) -> Dict[str, str]:
    now_utc = datetime.now(timezone.utc)
    defaults = {
        "FECHA_UTC": now_utc.strftime("%Y-%m-%d"),
        "HORA_MUESTREO_UTC": now_utc.strftime("%H:%M"),
        "VENTANA_UTC": f"{(now_utc.replace(hour=0, minute=0, second=0, microsecond=0)).strftime('%Y-%m-%d 00:00')}–{now_utc.strftime('%Y-%m-%d %H:%M')}",
        # Campos vacíos por si no llegan datos aún:
        "NUM_PROVEEDORES": data.get("NUM_PROVEEDORES", ""),
        "INC_NUEVOS_HOY": data.get("INC_NUEVOS_HOY", ""),
        "INC_ACTIVOS": data.get("INC_ACTIVOS", ""),
        "INC_RESUELTOS_HOY": data.get("INC_RESUELTOS_HOY", ""),
        "MANTENIMIENTOS_HOY": data.get("MANTENIMIENTOS_HOY", ""),
        "OBS_CLAVE": data.get("OBS_CLAVE", ""),
        "FILAS_INCIDENTES_HOY": data.get("FILAS_INCIDENTES_HOY", ""),
        "FILAS_INCIDENTES_15D": data.get("FILAS_INCIDENTES_15D", ""),
        "LISTA_FUENTES_CON_ENLACES": data.get("LISTA_FUENTES_CON_ENLACES", ""),
        "FIRMA_HTML": data.get("FIRMA_HTML", ""),
        # Compatibilidad con campos de texto plano
        "TABLA_INCIDENTES_HOY": data.get("TABLA_INCIDENTES_HOY", ""),
        "TABLA_INCIDENTES_15D": data.get("TABLA_INCIDENTES_15D", ""),
        "NOMBRE_CONTACTO": data.get("NOMBRE_CONTACTO", ""),
        "ENLACE_O_REFERENCIA_INTERNA": data.get("ENLACE_O_REFERENCIA_INTERNA", ""),
        "ENLACE_O_TEXTO_CRITERIOS": data.get("ENLACE_O_TEXTO_CRITERIOS", ""),
        "IMPACTO_CLIENTE_SI_NO": data.get("IMPACTO_CLIENTE_SI_NO", ""),
        "ACCION_SUGERIDA": data.get("ACCION_SUGERIDA", ""),
        "FECHA_SIGUIENTE_REPORTE": data.get("FECHA_SIGUIENTE_REPORTE", ""),
    }
    # Mezcla sin machacar datos existentes
    merged = {**defaults, **data}
    return merged

# ==== Main ====

def main():
    ap = argparse.ArgumentParser(description="Enviar plantillas DORA como mensaje 'pegable' a Telegram/Teams")
    ap.add_argument("--text-template", default="templates/dora_email.txt", help="Ruta a la plantilla en texto")
    ap.add_argument("--html-template", default="templates/dora_email.html", help="Ruta a la plantilla en HTML")
    ap.add_argument("--data", help="Ruta a JSON con placeholders {\"CLAVE\":\"valor\"}")
    ap.add_argument("--channels", default="telegram,teams", help="Canales a enviar: telegram,teams,both (coma-separado)")
    ap.add_argument("--also-text", action="store_true", help="Además del HTML, envía la versión de texto como segundo mensaje")
    args = ap.parse_args()

    data = inject_defaults(load_data(args.data))

    # Carga plantillas
    text_subject, text_body_tpl = load_text_template(args.text_template)
    html_subject, html_tpl = load_html_template(args.html_template)

    # Render
    text_body = render_placeholders(text_body_tpl, data)
    html_body = render_placeholders(html_tpl, data)

    # Determina subject a mostrar en chats
    subject = data.get("SUBJECT") or text_subject or html_subject or "DORA Daily Digest"

    # Prepara mensaje “pegable” (bloque de código)
    html_block = wrap_codeblock("html", html_body)

    # Envío
    selected = {c.strip().lower() for c in args.channels.split(",")}
    if "both" in selected:
        selected = {"telegram", "teams"}

    errors: List[str] = []

    if "telegram" in selected:
        try:
            # 1/2: HTML en bloque
            send_telegram(f"{subject}\n\n{html_block}", subject=subject)
            # 2/2: opcional, versión texto (útil como fallback)
            if args.also_text and text_body.strip():
                for chunk in chunk_text(f"{subject}\n\n{text_body}", limit=3900):
                    send_telegram(chunk, subject=subject)
        except Exception as e:
            errors.append(f"Telegram: {e}")

    if "teams" in selected:
        try:
            payload = f"**{subject}**\n\n{html_block}"
            send_teams(payload, subject=subject)
            if args.also_text and text_body.strip():
                send_teams(f"**{subject} (texto plano)**\n\n```\n{text_body}\n```", subject=subject)
        except Exception as e:
            errors.append(f"Teams: {e}")

    if errors:
        raise SystemExit(" | ".join(errors))

if __name__ == "__main__":
    main()
