#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from common.config import TELEGRAM_CHUNK_LIMIT, TELEGRAM_SEND_TIMEOUT, TEAMS_SEND_TIMEOUT
from common.templates import (
    SUBJECT_RE,
    load_text_template,
    load_html_template,
    render_placeholders,
    wrap_codeblock,
    chunk_text,
)

# ---------------- Utilities ----------------


def is_truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "y", "on")


# ---------------- Data helpers ----------------


def load_data(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: ("" if v is None else str(v)) for k, v in data.items()}


def _saludo_linea(now_utc: datetime) -> str:
    h = int(now_utc.strftime("%H"))
    if 6 <= h < 12:
        return "Buenos días,"
    if 12 <= h < 20:
        return "Buenas tardes,"
    return "Buenas noches,"


def inject_defaults(data: Dict[str, str]) -> Dict[str, str]:
    now_utc = datetime.now(timezone.utc)
    defaults = {
        "FECHA_UTC": now_utc.strftime("%Y-%m-%d"),
        "HORA_MUESTREO_UTC": now_utc.strftime("%H:%M"),
        "VENTANA_UTC": (
            f"{(now_utc.replace(hour=0, minute=0, second=0, microsecond=0)).strftime('%Y-%m-%d 00:00')}"
            f"–{now_utc.strftime('%Y-%m-%d %H:%M')}"
        ),
        "NUM_PROVEEDORES": data.get("NUM_PROVEEDORES", ""),
        "INC_NUEVOS_HOY": data.get("INC_NUEVOS_HOY", ""),
        "INC_ACTIVOS": data.get("INC_ACTIVOS", ""),
        "INC_RESUELTOS_HOY": data.get("INC_RESUELTOS_HOY", ""),
        "MANTENIMIENTOS_HOY": data.get("MANTENIMIENTOS_HOY", ""),
        "OBS_CLAVE": data.get("OBS_CLAVE", ""),
        "FILAS_INCIDENTES_HOY": data.get("FILAS_INCIDENTES_HOY", ""),
        "FILAS_INCIDENTES_15D": data.get("FILAS_INCIDENTES_15D", ""),
        "LISTA_FUENTES_CON_ENLACES": data.get("LISTA_FUENTES_CON_ENLACES", ""),
        "LISTA_FUENTES_TXT": data.get("LISTA_FUENTES_TXT", ""),
        "FIRMA_HTML": data.get("FIRMA_HTML", ""),
        "TABLA_INCIDENTES_HOY": data.get("TABLA_INCIDENTES_HOY", ""),
        "TABLA_INCIDENTES_15D": data.get("TABLA_INCIDENTES_15D", ""),
        "NOMBRE_CONTACTO": data.get("NOMBRE_CONTACTO", ""),
        "ENLACE_O_REFERENCIA_INTERNA": data.get("ENLACE_O_REFERENCIA_INTERNA", ""),
        "ENLACE_O_TEXTO_CRITERIOS": data.get("ENLACE_O_TEXTO_CRITERIOS", ""),
        "IMPACTO_CLIENTE_SI_NO": data.get("IMPACTO_CLIENTE_SI_NO", ""),
        "ACCION_SUGERIDA": data.get("ACCION_SUGERIDA", ""),
        "FECHA_SIGUIENTE_REPORTE": data.get("FECHA_SIGUIENTE_REPORTE", ""),
        "DETALLES_POR_VENDOR_TEXTO": data.get("DETALLES_POR_VENDOR_TEXTO", ""),
        "SALUDO_LINEA": data.get("SALUDO_LINEA") or _saludo_linea(now_utc),
    }
    return {**defaults, **data}


# ---------------- Senders (honour DRY-RUN) ----------------


def env_or_raise(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return val


def send_telegram(markdown: str, subject: Optional[str], dry_run: bool) -> None:
    if dry_run:
        return
    token = env_or_raise("TELEGRAM_BOT_TOKEN")
    chat_id = env_or_raise("TELEGRAM_USER_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in chunk_text(markdown, limit=TELEGRAM_CHUNK_LIMIT):
        r = requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=TELEGRAM_SEND_TIMEOUT)
        if r.status_code != 200:
            msg = r.text
            if len(msg) > 600:
                msg = msg[:600] + "...(truncado)"
            raise RuntimeError(f"Telegram error ({r.status_code}): {msg}")


def send_teams(markdown: str, subject: Optional[str], dry_run: bool) -> None:
    if dry_run:
        return
    webhook = env_or_raise("TEAMS_WEBHOOK_URL")
    title = subject or "DORA Daily Digest"
    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": title,
        "themeColor": "2B579A",
        "title": title,
        "text": markdown,
    }
    r = requests.post(webhook, json=card, timeout=TEAMS_SEND_TIMEOUT)
    if r.status_code >= 300:
        msg = r.text
        if len(msg) > 600:
            msg = msg[:600] + "...(truncado)"
        raise RuntimeError(f"Teams webhook error ({r.status_code}): {msg}")


# ---------------- Preview writers ----------------


def write_preview(
    preview_dir: str,
    subject: str,
    html_block_md: str,
    html_body: str,
    text_body: str,
) -> None:
    os.makedirs(preview_dir, exist_ok=True)
    with open(os.path.join(preview_dir, "subject.txt"), "w", encoding="utf-8") as f:
        f.write(subject)
    with open(os.path.join(preview_dir, "html_block.md"), "w", encoding="utf-8") as f:
        f.write(html_block_md)
    with open(os.path.join(preview_dir, "email.html"), "w", encoding="utf-8") as f:
        f.write(html_body)
    with open(os.path.join(preview_dir, "text_body.txt"), "w", encoding="utf-8") as f:
        f.write(text_body)


# ---------------- Main ----------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Enviar plantillas DORA como mensaje 'pegable' a Telegram/Teams"
    )
    ap.add_argument("--text-template", default="templates/dora_email.txt")
    ap.add_argument("--html-template", default="templates/dora_email.html")
    ap.add_argument("--data")
    ap.add_argument("--channels", default="telegram,teams", help="telegram,teams,both,none")
    ap.add_argument("--also-text", action="store_true")  # kept for compatibility, no longer affects preview
    ap.add_argument(
        "--preview-out",
        help="Directory to write preview files (subject/html/text). Implies no sending.",
    )
    args = ap.parse_args()

    data = inject_defaults(load_data(args.data))
    text_subject, text_body_tpl = load_text_template(args.text_template)
    html_subject, html_tpl = load_html_template(args.html_template)

    text_body = render_placeholders(text_body_tpl, data)
    html_body = render_placeholders(html_tpl, data)
    subject = data.get("SUBJECT") or text_subject or html_subject or "DORA Daily Digest"
    html_block = wrap_codeblock("html", html_body)

    # DRY-RUN if preview_out is set or NOTIFY_DRY_RUN env var is truthy
    dry_run = bool(args.preview_out) or is_truthy_env("NOTIFY_DRY_RUN")

    # Channel selection
    selected = {c.strip().lower() for c in args.channels.split(",") if c.strip()}
    if "both" in selected:
        selected = {"telegram", "teams"}
    if "none" in selected:
        selected = set()

    if dry_run:
        preview_dir = args.preview_out or ".github/out/preview"
        write_preview(preview_dir, subject, html_block, html_body, text_body)
        print(f"[preview] Escribí previsualización en: {preview_dir}")
        return

    errors: List[str] = []

    # Telegram → plain-text version
    if "telegram" in selected:
        try:
            for chunk in chunk_text(f"{subject}\n\n{text_body}", limit=TELEGRAM_CHUNK_LIMIT):
                send_telegram(chunk, subject=subject, dry_run=False)
        except Exception as e:
            errors.append(f"Telegram: {e}")

    # Teams → HTML block version
    if "teams" in selected:
        try:
            payload = f"**{subject}**\n\n{html_block}"
            send_teams(payload, subject=subject, dry_run=False)
        except Exception as e:
            errors.append(f"Teams: {e}")

    if errors:
        raise SystemExit(" | ".join(errors))


if __name__ == "__main__":
    main()
