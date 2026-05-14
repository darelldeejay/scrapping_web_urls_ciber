# common/utils.py
# -*- coding: utf-8 -*-
"""
Utilidades compartidas entre vendors: timestamps UTC y normalización de texto.

Centraliza funciones que antes se copiaban en cada vendor para evitar
divergencias y usos de datetime.utcnow() (deprecated en Python 3.12+).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone


def now_utc_str() -> str:
    """Timestamp UTC con sufijo 'UTC', para mensajes y notificaciones."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def now_utc_clean() -> str:
    """Timestamp UTC sin sufijo, para exportar a JSON (el digest añade 'UTC' al render)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


def collapse_ws(s: str) -> str:
    """Colapsa secuencias de espacios/saltos a un único espacio."""
    return re.sub(r"\s+", " ", s or "").strip()
