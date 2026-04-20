# 🔐 Configuración Privada del Cliente

Este repositorio está diseñado para ser **escalable y reutilizable para múltiples clientes** mientras mantiene **datos sensibles completamente privados**.

## Problema Resuelto

❌ **Antes**: Nombre del cliente hardcodeado en templates → Expone datos privados en GitHub público  
✅ **Ahora**: Configuración privada en `.env` → Repositorio genérico, datos privados seguros

## Cómo Funciona

1. **Repositorio público** (`scrapping_web_urls_ciber`) → Código genérico, reutilizable
2. **Archivo `.env` privado** → Contiene datos específicos del cliente (NUNCA se commitea a GitHub)
3. **GitHub Secrets** (en CI) → Variables sensibles para pipeline automático

```
Flujo de Datos Privados:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
.env (PRIVADO)        ← Contiene: CLIENT_NAME, EMAIL, etc.
    ↓
common/config.py      ← Lee variables
    ↓
Scripts (run_digest.py) ← Usa CONFIG para templates
    ↓
Email con nombre cliente ← Sale con "BANCO PICHINCHA" pero no está en GitHub
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Instalación para Nuevo Cliente

### Paso 1: Copiar plantilla de configuración

```bash
cp .env.example .env
```

### Paso 2: Editar `.env` con datos del cliente

```bash
# .env (NO commitear este archivo)
# ⚠️ IMPORTANTE: Reemplaza <CLIENTE> con tu cliente real
# Este archivo NUNCA se commitea a GitHub

CLIENT_NAME="<TU_CLIENTE>"
CLIENT_CODE="<CÓDIGO_CLIENTE>"
CLIENT_FULL_NAME="<TU_CLIENTE> - Monitoreo DORA ICT"
EMAIL_SUBJECT_PREFIX="[<TU_CLIENTE> - DORA]"
EMAIL_CONFIDENTIAL_FOOTER="Información exclusiva para uso interno <TU_CLIENTE>"
CONTACT_PERSON="Equipo de Seguridad ICT"
CONTACT_DEPARTMENT="Seguridad de Información"
CLIENT_PORTAL_URL="https://portal.<cliente>.com"
CLIENT_SUPPORT_EMAIL="security@<cliente>.com"
```

### Paso 3: Verificar configuración

```bash
python -c "from common.config import get_config; cfg = get_config(); print(cfg)"
# Output: ClientConfig(client_name='<TU_CLIENTE>', client_code='<CÓDIGO_CLIENTE>')
```

## Para GitHub Actions (CI)

Usa GitHub Secrets para configurar variables en producción:

1. **Settings → Secrets and variables → Actions → New repository secret**

Crear estos secrets:
```
CLIENT_NAME=<TU_CLIENTE>
CLIENT_CODE=<CÓDIGO_CLIENTE>
EMAIL_CONFIDENTIAL_FOOTER=Información exclusiva para <TU_CLIENTE>
```

2. **Workflow (`.github/workflows/status-check.yml`)** lee automáticamente:
```yaml
env:
  CLIENT_NAME: ${{ secrets.CLIENT_NAME }}
  CLIENT_CODE: ${{ secrets.CLIENT_CODE }}
  EMAIL_CONFIDENTIAL_FOOTER: ${{ secrets.EMAIL_CONFIDENTIAL_FOOTER }}
```

## Verificación de Seguridad

✅ `.env` está en `.gitignore` → No puede ser commiteado accidentalmente  
✅ Repositorio público NO contiene referencias al cliente  
✅ Reports salen con nombre del cliente (datos vienen de .env privado)  
✅ Escalable: cambiar `CLIENT_NAME` en `.env` genera reportes para otro cliente  

## Ejemplo: Migrar a Otro Cliente

Para usar este repositorio con otro cliente (ej: "Banco XYZ"):

```bash
# Solo cambiar el archivo .env
CLIENT_NAME="<OTRO_CLIENTE>"
CLIENT_CODE="<OTRO_CÓDIGO>"
# ... resto de configuración
```

Luego ejecutar los scripts:
```bash
python scripts/run_vendor.py --vendor aruba --export-json .github/out/vendors/aruba.json
python scripts/run_digest.py --data .github/out/digest_data.json
# Los reportes saldrán con el nombre del cliente configurado en .env
```

## Integración en Código Python

```python
from common.config import get_config

config = get_config()
print(f"Cliente: {config.client_name}")
print(f"Footer: {config.email_confidential_footer}")

# Para templates
vars = config.get_template_vars()
email_subject = config.get_email_subject("2026-04-20")
# Output: "[<TU_CLIENTE> - DORA] Informe diario de terceros ICT — 2026-04-20 (UTC)"
```

## Mejores Prácticas

1. **NUNCA** commitear `.env` real
2. **Siempre** usar `python -dotenv` o `common.config.load_env_file()`
3. **Para CI/CD** usar GitHub Secrets
4. **Para desarrollo local** usar `.env.local` (también en .gitignore)
5. **Documentar** en `.env.example` qué variables existen

## Preguntas Frecuentes

**P: ¿Y si alguien hace fork del repo?**  
R: El fork será completamente genérico. Necesitarán copiar `.env.example` a `.env` y configurar su cliente. Nada privado se expondrá.

**P: ¿Puedo tener múltiples clientes en el mismo repo?**  
R: Sí. Crea `.env.banco1`, `.env.banco2`, etc. y cambia el archivo antes de ejecutar.

**P: ¿Los datos sensibles aparecen en los logs de GitHub Actions?**  
R: No. Los secrets de GitHub Actions se enmascaran automáticamente en logs.

---

🔒 **Seguridad: PRIVACIDAD DEL CLIENTE GARANTIZADA**
