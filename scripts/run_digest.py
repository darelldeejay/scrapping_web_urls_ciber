#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple
import re
import requests
# Importar config para obtener datos del cliente
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from common.config import ClientConfig
from common.logger import setup_logging, get_logger
from common.templates import (
    load_text_template,
    load_html_template,
    render_placeholders,
    wrap_codeblock,
    chunk_text,
)

# ---------------- Utilidades ----------------

logger = get_logger(__name__)

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
        "DETALLES_POR_VENDOR_HTML": data.get("DETALLES_POR_VENDOR_HTML", ""),
        "SALUDO_LINEA": data.get("SALUDO_LINEA") or _saludo_linea(now_utc),
    }
    # Confidencial line: only render if the variable has a value
    conf_footer = data.get("EMAIL_CONFIDENTIAL_FOOTER", "").strip()
    defaults["CONFIDENCIAL_LINEA_HTML"] = (
        f"<strong>Confidencial:</strong> {conf_footer}<br>" if conf_footer else ""
    )
    return {**defaults, **data}

# ---------------- Senders (honran DRY-RUN) ----------------

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
    for chunk in chunk_text(markdown, limit=3900):
        r = requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=30)
        if r.status_code != 200:
            msg = r.text
            if len(msg) > 600:
                msg = msg[:600] + "...(truncado)"
            raise RuntimeError(f"Telegram error ({r.status_code}): {msg}")

def _build_teams_markdown(data: Dict[str, str], subject: str) -> str:
    """Construye un mensaje Markdown bien formateado para Teams.
    Teams renderiza Markdown nativo: negrita, encabezados, listas, separadores.
    """
    lines = [f"## {subject}", ""]

    # KPIs
    kpis = [
        ("🏢 Proveedores ICT", data.get("NUM_PROVEEDORES", "-")),
        ("🆕 Nuevos Hoy", data.get("INC_NUEVOS_HOY", "-")),
        ("🔴 Activos", data.get("INC_ACTIVOS", "-")),
        ("✅ Resueltos", data.get("INC_RESUELTOS", "-")),
        ("🔧 Mantenimientos", data.get("MANTENIMIENTOS_HOY", "-")),
    ]
    lines.append("| Métrica | Valor |")
    lines.append("|---|---|")
    for label, val in kpis:
        lines.append(f"| {label} | **{val}** |")
    lines.append("")

    # Observación clave
    obs = data.get("OBS_CLAVE", "").strip()
    if obs:
        lines.append(f"**Observación:** {obs}")
        lines.append("")

    # Detalle por vendor
    detalles = data.get("DETALLES_POR_VENDOR_TEXTO", "").strip()
    if detalles:
        lines.append("---")
        lines.append("### Detalle por fabricante")
        lines.append("")
        lines.append(detalles)
        lines.append("")

    # Recomendaciones
    recs = data.get("RECOMENDACIONES", "").strip()
    if recs:
        lines.append("---")
        lines.append("### Recomendaciones")
        lines.append("")
        lines.append(recs)
        lines.append("")

    # Pie
    fecha = data.get("FECHA_UTC", "")
    hora = data.get("HORA_MUESTREO_UTC", "")
    cliente = data.get("CLIENT_NAME", "")
    if cliente:
        lines.append(f"---")
        lines.append(f"*{cliente} · {fecha} {hora} UTC*")

    return "\n".join(lines)

def _simplify_html_for_teams(html: str) -> str:
    """Produce HTML limpio y simple para Teams.
    Teams renderiza: <h1-6>, <p>, <b>, <strong>, <i>, <em>, <u>, <br>,
    <table>, <tr>, <th>, <td>, <ul>, <ol>, <li>, <a href>, <img src>.
    Teams ELIMINA TODOS los estilos CSS (bloques <style> y atributos style="").
    Por tanto enviamos solo estructura semántica sin ningún CSS.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    # Eliminar etiquetas que Teams no necesita o no soporta
    for tag in soup.find_all(["style", "script", "head", "meta", "link"]):
        tag.decompose()

    body = soup.find("body") or soup

    # Eliminar atributos CSS (style y class) de todos los elementos
    for tag in body.find_all(True):
        tag.attrs = {
            k: v for k, v in (tag.attrs or {}).items()
            if k in ("href", "src", "alt", "colspan", "rowspan", "border", "cellpadding", "cellspacing")
        }

    return body.decode_contents()

def send_teams(html: str, subject: str, dry_run: bool) -> None:
    """Envía el digest via Power Automate webhook.
    El flujo de Power Automate envía el HTML por email al cliente (Office 365 Outlook)
    y publica una confirmación en el canal Teams del SOC.
    """
    if dry_run:
        return
    webhook = env_or_raise("TEAMS_WEBHOOK_URL")
    payload = {
        "subject": subject,
        "html":    html,
    }
    r = requests.post(webhook, json=payload, timeout=60)
    if r.status_code >= 300:
        msg = r.text
        if len(msg) > 600:
            msg = msg[:600] + "...(truncado)"
        raise RuntimeError(f"Teams webhook error ({r.status_code}): {msg}")

# ---------------- Preview writers ----------------

def write_preview(preview_dir: str, subject: str, html_block_md: str, html_body: str, text_body: str) -> None:
    os.makedirs(preview_dir, exist_ok=True)
    # Asunto
    with open(os.path.join(preview_dir, "subject.txt"), "w", encoding="utf-8") as f:
        f.write(subject)
    # HTML (bloque MD y archivo .html real)
    with open(os.path.join(preview_dir, "html_block.md"), "w", encoding="utf-8") as f:
        f.write(html_block_md)
    with open(os.path.join(preview_dir, "email.html"), "w", encoding="utf-8") as f:
        f.write(html_body)
    # TXT SIEMPRE (como antes)
    with open(os.path.join(preview_dir, "text_body.txt"), "w", encoding="utf-8") as f:
        f.write(text_body)

# ---------------- Main ----------------

def main():
    setup_logging()
    ap = argparse.ArgumentParser(description="Enviar plantillas DORA como mensaje 'pegable' a Telegram/Teams")
    ap.add_argument("--text-template", default="templates/dora_email.txt")
    ap.add_argument("--html-template", default="templates/dora_email.html")
    ap.add_argument("--data")
    ap.add_argument("--channels", default="telegram,teams", help="telegram,teams,both,none")
    ap.add_argument("--also-text", action="store_true")  # se mantiene por compatibilidad, pero ya no afecta al preview
    ap.add_argument("--preview-out", help="Directorio donde guardar previsualización (subject/html/text). Implica no enviar.")
    args = ap.parse_args()

    # Cargar datos del digest y del cliente
    digest_data = load_data(args.data)
    config = ClientConfig()
    client_vars = config.get_template_vars()
    # Combinar datos: prioridad a los datos de cliente si no existen en digest_data.json
    data = inject_defaults({**digest_data, **client_vars})

    text_subject, text_body_tpl = load_text_template(args.text_template)
    html_subject, html_tpl = load_html_template(args.html_template)

    text_body = render_placeholders(text_body_tpl, data)
    html_body = render_placeholders(html_tpl, data)
    # Renderizar el subject también (no solo text_body y html_body)
    subject = render_placeholders(data.get("SUBJECT") or text_subject or html_subject or "DORA Daily Digest", data)
    html_block = wrap_codeblock("html", html_body)

    # DRY-RUN si preview_out o env NOTIFY_DRY_RUN
    dry_run = bool(args.preview_out) or is_truthy_env("NOTIFY_DRY_RUN")

    # Selección de canales
    selected = {c.strip().lower() for c in args.channels.split(",") if c.strip()}
    if "both" in selected:
        selected = {"telegram", "teams"}
    if "none" in selected:
        selected = set()

    # Previsualización (no envío)
    if dry_run:
        preview_dir = args.preview_out or ".github/out/preview"
        # Siempre guardamos el cuerpo TXT (como estaba), y añadimos el HTML real.
        write_preview(preview_dir, subject, html_block, html_body, text_body)
        logger.info("Previsualizaci\u00f3n escrita en: %s", preview_dir)
        return

    errors: List[str] = []

    # Telegram → SOLO versión texto (como acordado)
    if "telegram" in selected:
        try:
            for chunk in chunk_text(f"{subject}\n\n{text_body}", limit=3900):
                send_telegram(chunk, subject=subject, dry_run=False)
        except Exception as e:
            errors.append(f"Telegram: {e}")

    # Teams → Power Automate envía el HTML por email al cliente y notifica al SOC en Teams
    if "teams" in selected:
        try:
            send_teams(html_body, subject=subject, dry_run=False)
        except Exception as e:
            errors.append(f"Teams: {e}")

    if errors:
        raise SystemExit(" | ".join(errors))

if __name__ == "__main__":
    main()
