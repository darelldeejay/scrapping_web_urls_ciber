# common/logger.py
# -*- coding: utf-8 -*-
"""
Factoría de loggers para toda la aplicación.

Uso:
    from common.logger import get_logger
    logger = get_logger(__name__)

    logger.info("Mensaje informativo")
    logger.warning("Advertencia")
    logger.error("Error")
    logger.exception("Error con traceback")  # incluye el traceback automáticamente

En producción (CI=true) el formato incluye timestamp para correlacionar líneas
en los logs de GitHub Actions. En local el formato es más compacto.

Nivel configurable con la variable de entorno LOG_LEVEL (default: INFO).
"""

from __future__ import annotations

import logging
import os

_configured = False


def setup_logging(default_level: str = "INFO") -> None:
    """
    Configura el logger raíz una sola vez.
    Llamar al inicio de cada script de entrada (run_vendor.py, run_digest.py…).
    Los módulos importados (vendors, common/) solo necesitan get_logger().
    """
    global _configured
    if _configured:
        return
    _configured = True

    is_ci = os.getenv("CI", "").lower() in ("true", "1")
    level_name = os.getenv("LOG_LEVEL", default_level).upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = (
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
        if is_ci
        else "[%(levelname)-8s] %(name)s: %(message)s"
    )
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S", force=True)


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger con nombre. Usar __name__ como convención."""
    return logging.getLogger(name)
