"""
config.py - Gestión centralizada de configuración del cliente.

Permite que el repositorio sea escalable para múltiples clientes
manteniendo datos sensibles privados en .env (no commiteado).
"""

import os
from pathlib import Path
from typing import Optional


class ClientConfig:
    """Configuración del cliente cargada desde .env"""

    def __init__(self):
        """Cargar configuración de variables de entorno (.env)"""
        self.client_name = os.getenv("CLIENT_NAME", "CLIENTE GENÉRICO")
        self.client_code = os.getenv("CLIENT_CODE", "GENERIC")
        self.client_full_name = os.getenv(
            "CLIENT_FULL_NAME", f"{self.client_name} - Monitoreo DORA ICT"
        )

        # Email
        self.email_subject_prefix = os.getenv(
            "EMAIL_SUBJECT_PREFIX", f"[{self.client_name} - DORA]"
        )
        self.email_confidential_footer = os.getenv(
            "EMAIL_CONFIDENTIAL_FOOTER",
            f"Información exclusiva para uso interno {self.client_name}",
        )

        # Contacto
        self.contact_person = os.getenv("CONTACT_PERSON", "Equipo de Seguridad")
        self.contact_department = os.getenv(
            "CONTACT_DEPARTMENT", "Seguridad de Información"
        )

        # URLs
        self.client_portal_url = os.getenv("CLIENT_PORTAL_URL", "")
        self.client_support_email = os.getenv("CLIENT_SUPPORT_EMAIL", "")

        # Notificaciones
        self.notify_to_telegram = os.getenv("NOTIFY_TO_TELEGRAM", "true").lower() == "true"
        self.notify_to_teams = os.getenv("NOTIFY_TO_TEAMS", "true").lower() == "true"

    def get_email_subject(self, fecha_utc: str) -> str:
        """Generar asunto del email con variables del cliente"""
        return f"{self.email_subject_prefix} Informe diario de terceros ICT — {fecha_utc} (UTC)"

    def get_template_vars(self) -> dict:
        """
        Retorna diccionario de variables para templates.
        Esto reemplaza {{VARIABLE}} en templates con valores del cliente.
        """
        return {
            "CLIENT_NAME": self.client_name,
            "CLIENT_CODE": self.client_code,
            "CLIENT_FULL_NAME": self.client_full_name,
            "EMAIL_SUBJECT_PREFIX": self.email_subject_prefix,
            "EMAIL_CONFIDENTIAL_FOOTER": self.email_confidential_footer,
            "CONTACT_PERSON": self.contact_person,
            "CONTACT_DEPARTMENT": self.contact_department,
            "CLIENT_PORTAL_URL": self.client_portal_url,
            "CLIENT_SUPPORT_EMAIL": self.client_support_email,
        }

    def validate(self) -> bool:
        """Validar que configuración necesaria esté presente"""
        if not self.client_name or self.client_name == "CLIENTE GENÉRICO":
            print(
                "⚠️  ADVERTENCIA: CLIENT_NAME no configurado. "
                "Copiar .env.example a .env y rellenar datos del cliente."
            )
            return False
        return True

    def __repr__(self) -> str:
        return (
            f"ClientConfig(client_name='{self.client_name}', "
            f"client_code='{self.client_code}')"
        )


# Instancia global de configuración (lazy load)
_config: Optional[ClientConfig] = None


def get_config() -> ClientConfig:
    """Obtener instancia global de configuración (singleton pattern)"""
    global _config
    if _config is None:
        _config = ClientConfig()
    return _config


def load_env_file(env_path: str = ".env") -> None:
    """
    Cargar variables de .env manualmente si python-dotenv no está disponible.
    (Alternativa si no quieres instalar dependencias adicionales)
    """
    env_file = Path(env_path)
    if not env_file.exists():
        print(f"⚠️  {env_path} no encontrado. Usando valores por defecto.")
        return

    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")
