# common/mailer.py
# -*- coding: utf-8 -*-
"""
Envío de correo vía SMTP (Gmail o servidor compatible).

Variables de entorno requeridas:
    SMTP_USER       Dirección de correo del remitente (ej: monitor@gmail.com)
    SMTP_PASSWORD   Contraseña de aplicación (Gmail: Ajustes > Seguridad > Contraseñas de app)
    EMAIL_TO        Dirección(es) destinataria(s), separadas por coma

Variables opcionales:
    SMTP_HOST       Servidor SMTP       (default: smtp.gmail.com)
    SMTP_PORT       Puerto TLS          (default: 587)
    EMAIL_FROM      Nombre del remitente (default: SMTP_USER)
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _is_truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "y", "on")


def send_email_smtp(
    subject: str,
    html_body: str,
    text_body: str = "",
) -> None:
    """
    Envía un correo con cuerpo HTML (y alternativa de texto plano).

    Si NOTIFY_DRY_RUN=1 o faltan credenciales, no envía nada.
    No lanza excepciones para no bloquear el flujo principal.
    """
    if _is_truthy_env("NOTIFY_DRY_RUN"):
        return

    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()
    email_to_raw = os.getenv("EMAIL_TO", "").strip()

    if not smtp_user or not smtp_pass or not email_to_raw:
        # Credenciales no configuradas: omitir silenciosamente
        return

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    email_from = os.getenv("EMAIL_FROM", smtp_user)
    recipients = [addr.strip() for addr in email_to_raw.split(",") if addr.strip()]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = ", ".join(recipients)

    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(email_from, recipients, msg.as_bytes())
    except Exception:
        # No propagamos errores de notificación para no bloquear el digest
        pass
