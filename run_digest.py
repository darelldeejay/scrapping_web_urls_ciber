#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import argparse
import requests
import re
from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple

# ---------------- Utils ----------------

def is_truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "y", "on")

SUBJECT_RE = re.compile(r"^\s*Asunto\s*:\s*(.+)\s*$", re.IGNORECASE)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-z0-9_]+)\s*}}")

def load_text_template(path: str) -> Tuple[Optional[str], str]:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    subject = None
    lines = raw.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        m = SUBJECT_RE.match(line)
        if m:
            subject = m.group(1).strip()
            body_start = i + 1
            break
    while body_start < len(lines) and lines[body_start].strip() == "":
        body_start += 1
    body = "\n".join(lines[body_start:]) if body_start < len(lines) else ""
    return subject, body

def load_html_template(path: str) -> Tuple[Optional[str], str]:
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    m = TITLE_RE.search(html)
    subject = m.group(1).strip() if m else None
    return subject, html

def render_placeholders(template: str, data: Dict[str, str]) -> str:
    def _rep(m):
        key = m.group(1)
        return str(data.get(key, m.group(0)))
    return PLACEHOLDER_RE.sub(_rep, template)

def wrap_codeblock(lang: str, content: str) -> str:
    safe = content.replace("```", "``\u200b`")
    return f"```{lang}\n{safe}\n```"

def chunk_text(text: str, limit: int = 3900):
    if len(text) <= limit:
        yield text
        return
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        nl = text.rfind("\n", start, end)
        if nl == -1 or nl <= start:
            nl = end
        yield text[start:nl]
        start = nl

# ---------------- Data helpers ----------------

def load_data(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: ("" if v is None else str(v)) for k, v in data.items()}

def inject_defaults(data: Dict[str, str]) -> Dict[str, str]:
    now_utc = datetime.now(timezone.utc)
    defaults = {
        "FECHA_UTC": now_utc.strftime("%Y-%m-%d"),
        "HORA_MUESTREO_UTC": now_utc.strftime("%H:%M"),
        "VENTANA_UTC": f"{(now_utc.replace(hour=0, minute=0, second=0, microsecond=0)).strftime('%Y-%m-%d 00:00')}–{now_utc.strftime('%Y-%m-%d %H:%M')}",
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
        "TABLA_INCIDENTES_HOY": data.get("TABLA_INCIDENTES_HOY", ""),
        "TABLA_INCIDENTES_15D": data.get("TABLA_INCIDENTES_15D", ""),
        "NOMBRE_CONTACTO": data.get("NOMBRE_CONTACTO", ""),
        "ENLACE_O_REFERENCIA_INTERNA": data.get("ENLACE_O_REFERENCIA_INTERNA", ""),
        "ENLACE_O_TEXTO_CRITERIOS": data.get("ENLACE_O_TEXTO_CRITERIOS", ""),
        "IMPACTO_CLIENTE_SI_NO": data.get("IMPACTO_CLIENTE_SI_NO", ""),
        "ACCION_SUGERIDA": data.get("ACCION_SUGERIDA", ""),
        "FECHA_SIGUIENTE_REPORTE": data.get("FECHA_SIGUIENTE_REPORTE", ""),
        "SALUDO_LINEA": data.get("SALUDO_LINEA", ""),
        "DETALLES_POR_VENDOR_TEXTO": data.get("DETALLES_POR_VENDOR_TEXTO", ""),
        "LISTA_FUENTES_URLS": data.get("LISTA_FUENTES_URLS", ""),
    }
    return {**defaults, **data}

# ---------------- Senders (resilientes) ----------------

def env_or_raise(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return val

def _retry_send(fn, attempts=3, delay_s=2) -> Tuple[bool, Optional[str]]:
    last_err = None
    for i in range(1, attempts + 1):
        try:
            fn()
            return True, None
        except Exception as e:
            last_err = str(e)
            if i < attempts:
                time.sleep(delay_s)
    return False, last_err

def send_telegram_text(text: str, dry_run: bool) -> Tuple[bool, Optional[str]]:
    if dry_run:
        print("[dry-run] Telegram (texto) no enviado (previsualización activa).")
        return True, None
    token = env_or_raise("TELEGRAM_BOT_TOKEN")
    chat_id = env_or_raise("TELEGRAM_USER_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    def _send_chunk(chunk: str):
        r = requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=30)
        if r.status_code != 200:
            msg = r.text
            if len(msg) > 600:
                msg = msg[:600] + "...(truncado)"
            raise RuntimeError(f"Telegram error ({r.status_code}): {msg}")

    # Enviar por chunks; si falla un chunk consideramos fallo del canal
    for chunk in chunk_text(text, limit=3900):
        ok, err = _retry_send(lambda: _send_chunk(chunk))
        if not ok:
            return False, err
    return True, None

def send_teams_html_block(markdown_with_codeblock: str, subject: str, dry_run: bool) -> Tuple[bool, Optional[str]]:
    if dry_run:
        print("[dry-run] Teams (HTML-bloque) no enviado (previsualización activa).")
        return True, None
    webhook = env_or_raise("TEAMS_WEBHOOK_URL")
    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": subject or "DORA Daily Digest",
        "themeColor": "2B579A",
        "title": subject or "DORA Daily Digest",
        "text": markdown_with_codeblock,
    }
    def _send():
        r = requests.post(webhook, json=card, timeout=30)
        if r.status_code >= 300:
            msg = r.text
            if len(msg) > 600:
                msg = msg[:600] + "...(truncado)"
            raise RuntimeError(f"Teams webhook error ({r.status_code}): {msg}")
    ok, err = _retry_send(_send)
    return ok, err

# ---------------- Preview writers ----------------

def write_preview(preview_dir: str, subject: str, html_block: str, text_body: str) -> None:
    os.makedirs(preview_dir, exist_ok=True)
    with open(os.path.join(preview_dir, "subject.txt"), "w", encoding="utf-8") as f:
        f.write(subject)
    with open(os.path.join(preview_dir, "html_block.md"), "w", encoding="utf-8") as f:
        f.write(html_block)
    if text_body.strip():
        with open(os.path.join(preview_dir, "text_body.txt"), "w", encoding="utf-8") as f:
            f.write(text_body)

# ---------------- Main ----------------

def main():
    ap = argparse.ArgumentParser(description="Enviar plantillas DORA a Telegram (texto) y Teams (HTML bloque pegable)")
    ap.add_argument("--text-template", default="templates/dora_email.txt")
    ap.add_argument("--html-template", default="templates/dora_email.html")
    ap.add_argument("--data")
    ap.add_argument("--channels", default="both", help="telegram,teams,both,none")
    ap.add_argument("--preview-out", help="Directorio para previsualización (subject/html/text). Implica no enviar.")
    ap.add_argument("--strict", action="store_true", help="Fallar el job si cualquier canal falla (por defecto NO falla si al menos uno tiene éxito)")
    args = ap.parse_args()

    data = inject_defaults(load_data(args.data))

    text_subject, text_body_tpl = load_text_template(args.text_template)
    html_subject, html_tpl = load_html_template(args.html_template)

    text_body = render_placeholders(text_body_tpl, data)
    html_body = render_placeholders(html_tpl, data)

    # Prioridad de subject: SUBJECT en data > subject en txt > title en html > fallback
    subject = data.get("SUBJECT") or text_subject or html_subject or "DORA Daily Digest"

    # Equipo: HTML como bloque "pegable"
    html_block = wrap_codeblock("html", html_body)

    # DRY-RUN si preview_out o env NOTIFY_DRY_RUN
    dry_run = bool(args.preview_out) or is_truthy_env("NOTIFY_DRY_RUN")

    # Selección de canales
    selected = {c.strip().lower() for c in (args.channels or "").split(",") if c.strip()}
    if "both" in selected or not selected:
        selected = {"telegram", "teams"}
    if "none" in selected:
        selected = set()

    # Previsualización
    if dry_run:
        preview_dir = args.preview_out or ".github/out/preview"
        # Guardamos el TXT que irá a Telegram y el bloque HTML que irá a Teams
        write_preview(preview_dir, subject, html_block, f"{subject}\n\n{text_body}")
        print(f"[preview] Escribí previsualización en: {preview_dir}")
        return

    any_success = False
    errors: List[str] = []

    # Telegram -> SOLO TEXTO
    if "telegram" in selected:
        payload_txt = f"{subject}\n\n{text_body}".strip()
        print("[send] Telegram: enviando texto…")
        ok, err = send_telegram_text(payload_txt, dry_run=False)
        if ok:
            any_success = True
            print("[ok] Telegram enviado.")
        else:
            errors.append(f"Telegram: {err or 'unknown error'}")
            print(f"[warn] Telegram fallo: {err}")

    # Teams -> BLOQUE HTML PEGABLE
    if "teams" in selected:
        payload_md = f"**{subject}**\n\n{html_block}"
        print("[send] Teams: enviando bloque HTML…")
        ok, err = send_teams_html_block(payload_md, subject=subject, dry_run=False)
        if ok:
            any_success = True
            print("[ok] Teams enviado.")
        else:
            errors.append(f"Teams: {err or 'unknown error'}")
            print(f"[warn] Teams fallo: {err}")

    # Política de salida:
    # - por defecto: si al menos un canal tuvo éxito -> exit 0 (no romper job)
    # - con --strict: fallar si ANY canal falló
    if errors:
        if args.strict or not any_success:
            raise SystemExit(" | ".join(errors))
        else:
            print("[warn] Hubo errores parciales pero al menos un canal se envió correctamente.")
    else:
        print("[ok] Envío completado sin errores.")

if __name__ == "__main__":
    main()
