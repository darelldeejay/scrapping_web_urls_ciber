#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple

import requests
from zoneinfo import ZoneInfo
import re
import html

def is_truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "y", "on")

# ---------------- Template helpers ----------------

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
        html_txt = f.read()
    m = TITLE_RE.search(html_txt)
    subject = m.group(1).strip() if m else None
    return subject, html_txt

def render_placeholders(template: str, data: Dict[str, str]) -> str:
    def _rep(m):
        key = m.group(1)
        return str(data.get(key, m.group(0)))
    return PLACEHOLDER_RE.sub(_rep, template)

def render_subject_candidate(s: Optional[str], data: Dict[str, str]) -> Optional[str]:
    if not s:
        return None
    return render_placeholders(s, data)

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

def compute_saludo_and_line(data: Dict[str, str]) -> tuple[str, str]:
    tzname = os.getenv("GREETING_TZ", "Europe/Madrid")
    try:
        now_local = datetime.now(ZoneInfo(tzname))
    except Exception:
        now_local = datetime.now()
    h = now_local.hour
    if 6 <= h < 12:
        saludo = "Buenos días"
    elif 12 <= h < 21:
        saludo = "Buenas tardes"
    else:
        saludo = "Buenas noches"
    nombre = (data.get("NOMBRE_CONTACTO") or "").strip()
    if nombre:
        saludo_linea = f"{saludo} {nombre},"
    else:
        saludo_linea = f"{saludo},"
    return saludo, saludo_linea

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
        "FUENTES_TEXTO": data.get("FUENTES_TEXTO", ""),
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
        "SALUDO": data.get("SALUDO", ""),
        "SALUDO_LINEA": data.get("SALUDO_LINEA", ""),
        "SUBJECT": data.get("SUBJECT", ""),
    }
    merged = {**defaults, **data}
    saludo, saludo_linea = compute_saludo_and_line(merged)
    merged["SALUDO"] = saludo
    merged["SALUDO_LINEA"] = saludo_linea
    return merged

# ---------------- HTML->TXT (listas conservando URLs) ----------------

LI_RE = re.compile(r"(?is)<li\b[^>]*>(.*?)</li\s*>")
TAGS_SIMPLE_RE = re.compile(r"(?is)</?(?:ul|ol)\b[^>]*>")
A_HREF_RE = re.compile(r'(?is)<a\b[^>]*\bhref=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a\s*>')

def _anchor_to_text(s: str) -> str:
    def repl(m: re.Match) -> str:
        url = m.group(1).strip()
        txt = m.group(2).strip()
        txt = re.sub(r"(?is)<[^>]+>", "", txt)
        return f"{html.unescape(txt)} ({url})"
    return A_HREF_RE.sub(repl, s)

def _html_list_to_text_bullets(s: str) -> str:
    """Convierte listas HTML a viñetas, preservando anchors como 'Texto (URL)'."""
    if not s or ("<li" not in s and "</li>" not in s):
        return s
    s = _anchor_to_text(s)
    def _one_li(m: re.Match) -> str:
        inner = m.group(1) or ""
        inner = re.sub(r"(?is)<[^>]+>", "", inner)
        inner = html.unescape(inner)
        inner = re.sub(r"[ \t]+", " ", inner).strip()
        if not inner:
            inner = "-"
        return f"- {inner}"
    out = LI_RE.sub(_one_li, s)
    out = TAGS_SIMPLE_RE.sub("", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out

# ---------------- Senders ----------------

def env_or_raise(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return val

def send_telegram_text(subject: str, text_body: str, dry_run: bool) -> None:
    if dry_run:
        return
    token = env_or_raise("TELEGRAM_BOT_TOKEN")
    chat_id = env_or_raise("TELEGRAM_USER_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    full = f"{subject}\n\n{text_body}".strip()
    for chunk in chunk_text(full, limit=3900):
        r = requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=30)
        if r.status_code != 200:
            msg = r.text
            if len(msg) > 600:
                msg = msg[:600] + "...(truncado)"
            raise RuntimeError(f"Telegram error ({r.status_code}): {msg}")

def send_teams_html(subject: str, html_block_md: str, dry_run: bool) -> None:
    if dry_run:
        return
    webhook = env_or_raise("TEAMS_WEBHOOK_URL")
    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": subject,
        "themeColor": "2B579A",
        "title": subject,
        "text": html_block_md
    }
    r = requests.post(webhook, json=card, timeout=30)
    if r.status_code >= 300:
        msg = r.text
        if len(msg) > 600:
            msg = msg[:600] + "...(truncado)"
        raise RuntimeError(f"Teams webhook error ({r.status_code}): {msg}")

# ---------------- Preview writers ----------------

def write_preview(preview_dir: str, subject: str, html_block_md: str, text_body: str, html_raw: str) -> None:
    os.makedirs(preview_dir, exist_ok=True)
    with open(os.path.join(preview_dir, "subject.txt"), "w", encoding="utf-8") as f:
        f.write(subject)
    with open(os.path.join(preview_dir, "html_block.md"), "w", encoding="utf-8") as f:
        f.write(html_block_md)
    with open(os.path.join(preview_dir, "text_body.txt"), "w", encoding="utf-8") as f:
        f.write(text_body)
    with open(os.path.join(preview_dir, "email.html"), "w", encoding="utf-8") as f:
        f.write(html_raw)

# ---------------- Main ----------------

def main():
    ap = argparse.ArgumentParser(description="Enviar plantillas DORA: Teams=HTML, Telegram=text")
    ap.add_argument("--text-template", default="templates/dora_email.txt")
    ap.add_argument("--html-template", default="templates/dora_email.html")
    ap.add_argument("--data")
    ap.add_argument("--channels", default="telegram,teams", help="telegram,teams,both,none")
    ap.add_argument("--preview-out", help="Directorio para previsualización (no envía)")
    ap.add_argument("--also-text", action="store_true", help="(compat) ignorado; Telegram ya recibe texto")
    args = ap.parse_args()

    data = inject_defaults(load_data(args.data))

    text_subject_tpl, text_body_tpl = load_text_template(args.text_template)
    html_subject_tpl, html_tpl = load_html_template(args.html_template)

    text_body = render_placeholders(text_body_tpl, data)
    html_body = render_placeholders(html_tpl, data)

    # Conversión de listas HTML -> bullets en TXT (preserva URLs)
    if "<li" in text_body or "</li>" in text_body:
        text_body = _html_list_to_text_bullets(text_body)

    subject_override = render_subject_candidate(data.get("SUBJECT"), data)
    text_subject = render_subject_candidate(text_subject_tpl, data)
    html_subject = render_subject_candidate(html_subject_tpl, data)
    subject = subject_override or text_subject or html_subject or "DORA Daily Digest"

    html_block_md = wrap_codeblock("html", html_body)
    dry_run = bool(args.preview_out) or is_truthy_env("NOTIFY_DRY_RUN")

    selected = {c.strip().lower() for c in args.channels.split(",") if c.strip()}
    if "both" in selected:
        selected = {"telegram", "teams"}
    if "none" in selected:
        selected = set()

    if dry_run:
        preview_dir = args.preview_out or ".github/out/preview"
        write_preview(preview_dir, subject, html_block_md, f"{subject}\n\n{text_body}", html_body)
        print(f"[preview] Escribí previsualización en: {preview_dir}")
        return

    errors: List[str] = []

    if "telegram" in selected:
        try:
            send_telegram_text(subject, text_body, dry_run=False)
        except Exception as e:
            errors.append(f"Telegram: {e}")

    if "teams" in selected:
        try:
            send_teams_html(subject, html_block_md, dry_run=False)
        except Exception as e:
            errors.append(f"Teams: {e}")

    if errors:
        raise SystemExit(" | ".join(errors))

if __name__ == "__main__":
    main()
