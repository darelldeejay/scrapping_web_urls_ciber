# 📖 Documentación Local — Scrapping WEB · Monitor DORA ICT

> **Generada:** Mayo 2026 | **Repositorio:** `darelldeejay/scrapping_web_urls_ciber`

---

## 🎯 ¿Para qué sirve este proyecto?

Este proyecto implementa un **monitor de resiliencia operativa (DORA)** que:

1. **Scrapea automáticamente** las páginas de estado de 8 fabricantes ICT cada mañana a las 08:30 (hora Madrid).
2. **Normaliza y consolida** los incidentes, mantenimientos y estado global de cada vendor.
3. **Envía un informe diario** por dos canales:
   - **Telegram** → texto plano (cuerpo del correo electrónico).
   - **Microsoft Teams** → bloque HTML listo para copiar/pegar como correo al cliente.

El objetivo es cumplir con la práctica de **monitoreo de terceros ICT** exigida por el Reglamento Europeo DORA (Digital Operational Resilience Act), automatizando la recogida diaria de evidencias de estado de los proveedores críticos.

---

## 🧱 Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────────────┐
│                  GitHub Actions (CRON 08:30 Madrid)             │
│                                                                 │
│  Job: vendors (8 en paralelo, matrix strategy)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐  ...  ┌──────────┐    │
│  │ aruba.py │ │netskope  │ │qualys.py │       │trendmicro│    │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘       └────┬─────┘    │
│       │             │             │                   │         │
│       └─────────────┴─────────────┴───────────────────┘         │
│                          ↓                                      │
│              .github/out/vendors/*.json                         │
│                          ↓                                      │
│  Job: digest                                                    │
│  ├─→ build_digest_data.py  (consolida JSONs)                    │
│  ├─→ validate_digest.py    (verifica integridad)                │
│  └─→ run_digest.py         (renderiza plantillas y envía)       │
│                          ↓                                      │
│               Telegram (TXT) + Teams (HTML)                     │
└─────────────────────────────────────────────────────────────────┘
```

### Stack tecnológico

| Componente | Tecnología |
|---|---|
| Lenguaje | Python 3.10 |
| Scraping | Selenium 4.20 (Chrome headless) + BeautifulSoup 4 |
| HTML parsing | lxml, html.parser |
| Fechas/horas | python-dateutil, datetime UTC |
| Plantillas | Jinja2 |
| Notificaciones | requests (Telegram Bot API / Teams Webhook) |
| CI/CD | GitHub Actions (matrix + cron) |

---

## 📦 Vendors monitorizados

| Vendor | Archivo | URL de estado |
|---|---|---|
| Aruba Central | `vendors/aruba.py` | status.arubanetworks.com |
| CyberArk Privilege Cloud | `vendors/cyberark.py` | status.cyberark.com |
| Akamai (Guardicore) | `vendors/guardicore.py` | status.akamai.com |
| Imperva | `vendors/imperva.py` | status.imperva.com |
| Netskope | `vendors/netskope.py` | status.netskope.com |
| Proofpoint | `vendors/proofpoint.py` | status.proofpoint.com |
| Qualys | `vendors/qualys.py` | status.qualys.com |
| Trend Micro (Cloud One + Vision One) | `vendors/trendmicro.py` | status.trendmicro.com |

---

## 📁 Estructura de directorios

```
scrapping_web_urls_ciber/
│
├── vendors/                   # Un módulo Python por vendor
│   ├── aruba.py
│   ├── cyberark.py
│   ├── guardicore.py
│   ├── imperva.py
│   ├── netskope.py
│   ├── proofpoint.py
│   ├── qualys.py
│   └── trendmicro.py
│
├── common/                    # Módulos compartidos
│   ├── browser.py             # Selenium: arranque de Chrome headless
│   ├── config.py              # Configuración centralizada desde .env
│   ├── digest_export.py       # Exportación de datos del digest
│   ├── fallback_collectors.py # Collectors alternativos (resiliencia)
│   ├── format.py              # Helpers de formato (cabeceras, listas)
│   ├── notify.py              # Envío a Telegram y Teams
│   ├── statuspage.py          # Integración genérica con statuspage.io
│   └── templates.py           # Motor de renderizado de plantillas
│
├── scripts/                   # Scripts orquestadores
│   ├── run_vendor.py          # Ejecuta un vendor y exporta JSON
│   ├── run_digest.py          # Renderiza y envía el digest
│   ├── build_digest_data.py   # Consolida JSONs de vendors
│   ├── validate_digest.py     # Valida integridad del digest
│   ├── diagnose.py            # Diagnóstico de problemas
│   ├── debug_vendors.py       # Debug detallado de vendors
│   └── run_vendor_debug.py    # Debug con captura de HTML
│
├── templates/                 # Plantillas de email
│   ├── dora_email.txt         # Versión texto plano (Telegram)
│   └── dora_email.html        # Versión HTML (Teams/correo)
│
├── docs/                      # Documentación técnica adicional
│   ├── DIAGNOSTICO_DEFINITIVO.md
│   ├── PRIVATE_CONFIG.md
│   ├── TIMEOUT_AND_CI_FIX.md
│   └── TROUBLESHOOTING_BLANK_DIGEST.md
│
├── .github/
│   └── workflows/
│       └── status-check.yml   # Pipeline CI/CD principal
│
├── .env.example               # Plantilla de configuración (sin datos reales)
├── .env                       # ⚠️ PRIVADO — nunca commitear (en .gitignore)
├── requirements.txt
├── README.md
├── STRUCTURE.md
├── SETUP_LOCAL.md
└── CONFIGURACION_CRITICA.md
```

---

## ⚙️ Configuración inicial (primera vez)

### 1. Instalar dependencias Python

```bash
pip install -r requirements.txt
```

También necesitas **Google Chrome** y **Chromedriver** instalados. En local, `webdriver-manager` los descarga automáticamente.

### 2. Crear el archivo `.env`

```bash
# Windows PowerShell
Copy-Item .env.example .env
```

Edita `.env` con los datos de tu cliente (este archivo es PRIVADO, nunca va a GitHub):

```env
CLIENT_NAME="NOMBRE DE TU CLIENTE"
CLIENT_CODE="CODIGO_CLIENTE"
CLIENT_FULL_NAME="NOMBRE CLIENTE - Monitoreo DORA ICT"

EMAIL_SUBJECT_PREFIX="[CLIENTE - DORA]"
EMAIL_CONFIDENTIAL_FOOTER="Información exclusiva para uso interno CLIENTE"

CONTACT_PERSON="Equipo de Seguridad ICT"
CONTACT_DEPARTMENT="Seguridad de Información"

CLIENT_PORTAL_URL="https://security.cliente.com"
CLIENT_SUPPORT_EMAIL="security@cliente.com"

NOTIFY_TO_TELEGRAM=true
NOTIFY_TO_TEAMS=true
```

### 3. Configurar secretos de notificación

Para las notificaciones necesitas configurar también en `.env` (o como variables de entorno):

```env
TELEGRAM_BOT_TOKEN=123456789:ABC-DEF...
TELEGRAM_USER_ID=987654321
TEAMS_WEBHOOK_URL=https://outlook.webhook.office.com/webhookb2/...
```

> **Cómo obtenerlos:**
> - **Telegram**: Habla con `@BotFather` en Telegram → `/newbot` → copia el token. Tu `USER_ID` lo obtienes con `@userinfobot`.
> - **Teams**: Canal de Teams → `···` → Conectores → Webhook entrante → copia la URL.

### 4. Verificar la configuración

```bash
python -c "from common.config import get_config; c = get_config(); print(f'✅ Configurado para: {c.client_name}')"
```

---

## 🚀 Uso en local

### Ejecutar un vendor individual

```bash
# Solo muestra el resultado en consola (y envía si NOTIFY_DRY_RUN != true)
python scripts/run_vendor.py --vendor netskope

# Exportar el resultado a JSON (necesario para el digest)
python scripts/run_vendor.py --vendor netskope --export-json .github/out/vendors/netskope.json
```

Vendors disponibles: `aruba`, `cyberark`, `guardicore`, `imperva`, `netskope`, `proofpoint`, `qualys`, `trendmicro`

### Ejecutar todos los vendors y construir el digest (sin enviar)

```bash
# 1. Crear directorio de salida
mkdir -p .github/out/vendors

# 2. Ejecutar todos los vendors
python scripts/run_vendor.py --vendor aruba      --export-json .github/out/vendors/aruba.json
python scripts/run_vendor.py --vendor cyberark   --export-json .github/out/vendors/cyberark.json
python scripts/run_vendor.py --vendor guardicore --export-json .github/out/vendors/guardicore.json
python scripts/run_vendor.py --vendor imperva    --export-json .github/out/vendors/imperva.json
python scripts/run_vendor.py --vendor netskope   --export-json .github/out/vendors/netskope.json
python scripts/run_vendor.py --vendor proofpoint --export-json .github/out/vendors/proofpoint.json
python scripts/run_vendor.py --vendor qualys     --export-json .github/out/vendors/qualys.json
python scripts/run_vendor.py --vendor trendmicro --export-json .github/out/vendors/trendmicro.json

# 3. Consolidar datos
python scripts/build_digest_data.py --vendors-dir .github/out/vendors --out .github/out/digest_data.json

# 4. Previsualizar digest SIN enviar
$env:NOTIFY_DRY_RUN="true"
python scripts/run_digest.py \
  --text-template templates/dora_email.txt \
  --html-template templates/dora_email.html \
  --data .github/out/digest_data.json \
  --channels both \
  --preview-out .github/out/preview
```

Los artefactos de previsualización quedan en `.github/out/preview/`:
- `subject.txt` — Asunto del email
- `text_body.txt` — Cuerpo en texto plano
- `email.html` — Email HTML renderizado

### Enviar el digest a un canal específico

```bash
# Solo Telegram
python scripts/run_digest.py --channels telegram --data .github/out/digest_data.json ...

# Solo Teams
python scripts/run_digest.py --channels teams --data .github/out/digest_data.json ...

# Ambos
python scripts/run_digest.py --channels both --data .github/out/digest_data.json ...
```

### Debug de un vendor (captura HTML para ajustar selectores)

```bash
# Guarda el HTML descargado para inspección manual
$env:SAVE_HTML="1"
python scripts/run_vendor_debug.py --vendor qualys
```

---

## 🤖 CI/CD en GitHub Actions

El workflow `.github/workflows/status-check.yml` se ejecuta:

| Trigger | Horario | Descripción |
|---|---|---|
| CRON verano (CEST) | `30 6 * * *` UTC | 08:30 hora Madrid (verano) |
| CRON invierno (CET) | `30 7 * * *` UTC | 08:30 hora Madrid (invierno) |
| Manual | `workflow_dispatch` | Con parámetros configurables |

### Parámetros del dispatch manual

| Parámetro | Opciones | Por defecto |
|---|---|---|
| `send_channels` | `none / telegram / teams / both` | `both` |
| `dry_run` | `true / false` | `false` |

### Secrets requeridos en GitHub

Ir a: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Descripción |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram |
| `TELEGRAM_USER_ID` | Chat ID de destino en Telegram |
| `TEAMS_WEBHOOK_URL` | URL del Webhook de Microsoft Teams |
| `CLIENT_NAME` | Nombre del cliente (aparece en el informe) |
| `CLIENT_CODE` | Código interno del cliente |
| `EMAIL_CONFIDENTIAL_FOOTER` | Pie de página de confidencialidad |

> **Nota:** GitHub deshabilita workflows automáticamente después de **60 días de inactividad**. Para reactivar: Actions → status-check → Enable workflow.

---

## 📝 Plantillas de informe

Las plantillas están en `templates/` y usan placeholders `{{VARIABLE}}`:

### Variables principales

| Variable | Descripción |
|---|---|
| `SALUDO_LINEA` | Buenos días/tardes/noches (según UTC) |
| `FECHA_UTC` | Fecha del informe en UTC |
| `HORA_MUESTREO_UTC` | Hora del muestreo en UTC |
| `VENTANA_UTC` | Ventana temporal cubierta |
| `NUM_PROVEEDORES` | Número de vendors monitorizados |
| `INC_NUEVOS_HOY` | Incidentes nuevos en las últimas 24h |
| `INC_ACTIVOS` | Incidentes activos en este momento |
| `INC_RESUELTOS_HOY` | Incidentes resueltos hoy |
| `MANTENIMIENTOS_HOY` | Mantenimientos programados hoy |
| `DETALLES_POR_VENDOR_TEXTO` | Bloque de texto con estado de cada vendor |
| `LISTA_FUENTES_TXT` | Fuentes en texto plano |
| `LISTA_FUENTES_CON_ENLACES` | Fuentes como `<li><a>` para HTML |
| `CLIENT_NAME` | Nombre del cliente |
| `EMAIL_CONFIDENTIAL_FOOTER` | Pie de confidencialidad |

---

## ➕ Añadir un nuevo vendor

1. **Crea** `vendors/<nombre>.py` con una función `run()`:

```python
from common.browser import start_driver
from bs4 import BeautifulSoup

def run():
    driver = start_driver()
    try:
        driver.get("https://status.ejemplo.com")
        # ... lógica de scraping ...
        soup = BeautifulSoup(driver.page_source, "lxml")
        # ... parsear estado ...
        return {
            "vendor": "Ejemplo",
            "status": "Operational",
            "incidents": [],
            "maintenances": []
        }
    finally:
        driver.quit()
```

2. **Añádelo a la matriz** del workflow en `.github/workflows/status-check.yml`:

```yaml
strategy:
  matrix:
    vendor: [aruba, cyberark, guardicore, imperva, netskope, proofpoint, qualys, trendmicro, ejemplo]
```

3. **Úsalo en local** con `python scripts/run_vendor.py --vendor ejemplo`.

### Normas de los parsers

- Tiempos siempre en **UTC**.
- Mensaje siempre presente: si no hay incidentes → `"No incidents in the last 24h"`.
- Usar `common/browser.py` para el driver (gestiona timeouts CI vs local).
- Evitar falsos positivos: revisar reglas de normalización en vendor similar.

---

## 🩺 Troubleshooting

### El digest llega en blanco / sin datos

Ver `docs/TROUBLESHOOTING_BLANK_DIGEST.md` y `docs/DIAGNOSTICO_DEFINITIVO.md`.

**Causa más frecuente:** Los artefactos JSON de vendors no se transfieren entre jobs.

```bash
# Verificar localmente si los JSONs tienen datos
python scripts/validate_digest.py --data .github/out/digest_data.json
```

### El workflow del CRON no se ejecuta

GitHub deshabilita workflows después de 60 días de inactividad:
1. Ir a **Actions** en GitHub
2. Seleccionar **status-check**
3. Clic en **Enable workflow**
4. Ejecutar manualmente para validar

### Error: `Network is unreachable` al enviar a Telegram en CI

El runner de GitHub no tiene salida a Internet. Usar `dry_run=true` para validar el output mientras se resuelve la conectividad.

### Error: `ModuleNotFoundError: No module named 'common'`

Asegúrate de ejecutar los scripts desde la raíz del repositorio:

```bash
cd "c:\Users\darelldeejay\OneDrive\Gitea\Propios\Scrapping DORA"
python scripts/run_vendor.py --vendor netskope
```

### El HTML del correo se muestra "todo seguido" sin saltos de línea

La plantilla HTML debe usar `<pre class="mono" style="white-space: pre-wrap">` alrededor del bloque `{{DETALLES_POR_VENDOR_TEXTO}}`.

### Necesito ver el DOM para ajustar los selectores de un vendor

```bash
$env:SAVE_HTML="1"
python scripts/run_vendor_debug.py --vendor <nombre>
# El HTML descargado queda en el workspace para inspección
```

---

## 🔐 Seguridad y buenas prácticas

- El archivo `.env` **nunca se commitea** (está en `.gitignore`).
- Los tokens de Telegram y URLs de Teams son secretos; usar siempre GitHub Secrets en producción.
- Chrome headless no guarda cookies ni sesiones entre ejecuciones.
- Los artefactos `.github/out/` están en `.gitignore` (datos transitorios de CI).
- El `CLIENT_NAME` en el informe final permite identificar el cliente sin exponer datos técnicos.

---

## 🔄 Flujo de trabajo local → GitHub

```bash
# 1. Hacer cambios en local (editar vendors, plantillas, etc.)

# 2. Probar localmente
python scripts/run_vendor.py --vendor <vendor_modificado>

# 3. Validar digest completo en dry-run
$env:NOTIFY_DRY_RUN="true"
python scripts/run_digest.py --channels both --data .github/out/digest_data.json ...

# 4. Commitear y subir
git add .
git commit -m "feat: descripción del cambio"
git push origin main

# 5. Verificar en GitHub Actions que el workflow pasa correctamente
```

---

## 📚 Referencias y documentación adicional

| Documento | Descripción |
|---|---|
| `README.md` | Documentación principal del repositorio |
| `STRUCTURE.md` | Arquitectura detallada de archivos |
| `SETUP_LOCAL.md` | Guía de configuración del cliente |
| `CONFIGURACION_CRITICA.md` | Pasos críticos de configuración |
| `docs/DIAGNOSTICO_DEFINITIVO.md` | Diagnóstico de problemas de CRON vs manual |
| `docs/TIMEOUT_AND_CI_FIX.md` | Solución a timeouts en CI |
| `docs/TROUBLESHOOTING_BLANK_DIGEST.md` | Resolución de digest en blanco |
| `.env.example` | Plantilla de configuración de cliente |
| `CONFIGURACION_LOCAL.md.example` | Ejemplo extendido de configuración local |
