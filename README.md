# Scrapping WEB · Monitor diario de terceros ICT (DORA)

Este proyecto realiza **scraping** de páginas de estado de fabricantes ICT, normaliza los resultados y envía un **informe diario** (texto a **Telegram** y HTML a **Microsoft Teams**) alineado con prácticas de **resiliencia operativa (DORA)**.

- ⚙️ **Stack**: Python 3.10 · Selenium (Chrome headless) · BeautifulSoup · dateutil
- 🔔 **Notificaciones**: por vendor (mensajes compactos) + **digest** diario (plantillas TXT/HTML “pegables”)
- ⏰ **CI/CD**: GitHub Actions con cron 08:30 Madrid (CET/CEST), artefactos de previsualización

---

## 📌 TL;DR

```bash
# 1) Instalar dependencias
pip install -r requirements.txt

# 2) Ejecutar un vendor y exportar JSON (para el digest)
python run_vendor.py --vendor netskope
python run_vendor.py --vendor netskope --export-json .github/out/vendors/netskope.json

# 3) Construir datos del digest y previsualizar sin enviar
python scripts/build_digest_data.py --vendors-dir .github/out/vendors --out .github/out/digest_data.json
NOTIFY_DRY_RUN=true python run_digest.py   --text-template templates/dora_email.txt   --html-template templates/dora_email.html   --data .github/out/digest_data.json   --channels both   --preview-out .github/out/preview
# Artefactos locales: .github/out/preview/subject.txt, text_body.txt, email.html
```

> En CI no necesitas ejecutar nada local: el workflow hace todo por ti (ver más abajo).

---

## ✨ Características

- **Scraping resiliente** (esperas inteligentes, tolerante a cambios menores de DOM).
- **Normalización por vendor** con reglas específicas (evitar falsos positivos, tiempos a UTC, etc.).
- **Mensajes por vendor** (siempre se envía algo: “No incidents…” cuando aplica).
- **Digest diario** consolidado:
  - **Telegram** → **texto** (cuerpo del correo en formato plano).
  - **Teams** → **bloque HTML** listo para copiar/pegar como correo.
- **Plantillas** en `templates/` con placeholders personalizables.
- **Vista previa segura** (artefactos `subject.txt`, `text_body.txt`, `email.html`) sin enviar.

---

## 🧱 Arquitectura

```
common/
  browser.py      # arranque Selenium (Chrome headless)
  notify.py       # envío Telegram/Teams
  format.py       # helpers de formato comunes (cabeceras, listas, etc.)
vendors/
  aruba.py        # Aruba Central
  cyberark.py     # CyberArk Privilege Cloud
  guardicore.py   # Akamai (Guardicore)
  imperva.py      # Imperva
  netskope.py     # Netskope
  proofpoint.py   # Proofpoint
  qualys.py       # Qualys
  trendmicro.py   # Trend Micro (Cloud One / Vision One)
scripts/
  build_digest_data.py  # agrega los JSON por vendor → digest_data.json
templates/
  dora_email.txt  # plantilla de correo en texto
  dora_email.html # plantilla de correo en HTML (pegable)
run_vendor.py     # orquesta ejecución por vendor (+ export JSON)
run_digest.py     # renderiza plantillas y envía a canales
.github/workflows/status-check.yml  # pipeline CI
requirements.txt
```

---

## 🔐 Configuración

### Requisitos
- Python **3.10**
- **Chromium + Chromedriver** (el workflow los instala automáticamente)

### Secrets (GitHub → Settings → Secrets y variables → Actions)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_USER_ID`
- `TEAMS_WEBHOOK_URL`

---

## 🚀 Uso en GitHub Actions

Workflow: `.github/workflows/status-check.yml`

- **Triggers**:
  - Manual (**Run workflow**) con inputs:
    - **Dónde enviar**: `none | telegram | teams | both`
    - **Solo previsualización (no envía)**: `true/false`
    - **Incluir versión de texto en el mensaje** (compatibilidad): opcional
  - Programado para **08:30 Madrid**:
    - `30 6 * * *` (verano, CEST)
    - `30 7 * * *` (invierno, CET)

- **Jobs**:
  1. `vendors` (matriz): ejecuta cada vendor, envía su mensaje y exporta `.json` a `.github/out/vendors/<vendor>.json` (artefacto `vendor-<vendor>`).
  2. `digest`: descarga todos los JSON, construye `digest_data.json` y ejecuta `run_digest.py`.
     - Si marcas “Solo previsualización”, **no envía** y sube artefacto `digest-preview` con:
       - `subject.txt` · `text_body.txt` · `email.html` · `html_block.md` · `digest_data.json`.

> **Canales**: Telegram recibe **TXT**; Teams recibe **HTML**.  
> Puedes elegir `both`, `telegram`, `teams` o `none` (solo preview).

---

## 🧩 Plantillas

- **Texto**: `templates/dora_email.txt`
  - Soporta asunto en la primera línea con `Asunto: ...`
  - Variables principales:
    - `SALUDO_LINEA` (Buenos días/tardes/noches en UTC)
    - `VENTANA_UTC`, `FECHA_UTC`, `HORA_MUESTREO_UTC`
    - `NUM_PROVEEDORES`, `INC_NUEVOS_HOY`, `INC_ACTIVOS`, `INC_RESUELTOS_HOY`, `MANTENIMIENTOS_HOY`
    - `DETALLES_POR_VENDOR_TEXTO` (siempre muestra el resumen por vendor, aunque estén en verde)
    - `OBS_CLAVE`, `IMPACTO_CLIENTE_SI_NO`, `ACCION_SUGERIDA`, `FECHA_SIGUIENTE_REPORTE`
    - `LISTA_FUENTES_TXT`

- **HTML**: `templates/dora_email.html`
  - Encabezado, saludo, meta y **“Detalles por fabricante”** con:
    ```html
    <pre class="mono">{{DETALLES_POR_VENDOR_TEXTO}}</pre>
    ```
    (usa `white-space: pre-wrap;` para respetar los saltos de línea)
  - Fuentes: `{{LISTA_FUENTES_CON_ENLACES}}` (lista `<li><a ...>Nombre</a></li>`)

> `run_digest.py` rellena automáticamente los placeholders. Si un valor no está, deja vacío sin romper.

---

## 🧪 Ejecución local (opcional)

```bash
# Instalar dependencias
pip install -r requirements.txt

# Ejecutar vendor (envía a canales si has configurado secrets en el entorno)
python run_vendor.py --vendor guardicore

# Exportar JSON de vendor (para digest)
python run_vendor.py --vendor guardicore --export-json .github/out/vendors/guardicore.json

# Construir y previsualizar digest (sin enviar)
python scripts/build_digest_data.py --vendors-dir .github/out/vendors --out .github/out/digest_data.json
NOTIFY_DRY_RUN=true python run_digest.py   --text-template templates/dora_email.txt   --html-template templates/dora_email.html   --data .github/out/digest_data.json   --channels both   --preview-out .github/out/preview
```

**Flags útiles**
- `NOTIFY_DRY_RUN=true` → previsualiza sin enviar
- `SAVE_HTML=1` en el job de vendors → guarda el HTML descargado para depurar parsers

---

## 🏭 Reglas por Vendor (resumen)

- **Akamai (Guardicore)**: vista compacta por grupos; “Incidents today” del día; manejo de páginas pesadas con timeout + `window.stop()`.
- **Netskope**: “Open Incidents” + “Past Incidents (Previous 15 days)”; evita falsos activos si hay **Resolved**; inicio/fin por **Investigating/Resolved**.
- **Proofpoint**: banner “Current Incidents” (habitual: “No current identified incidents”); si listaran incidentes, solo `Incident ####`.
- **Qualys**: histórico mensual; **descarta [Scheduled]**; convierte rangos de hora a **UTC**.
- **Aruba**: confirma “All components Operational” si aplica; mantiene textos en inglés del sitio.
- **Imperva**: lista **componentes no-operacionales** + POPs cuando aplica; “Overall status” verde cuando todo OK; solo HOY.
- **CyberArk**: “All Systems Operational” + “Incidents today” sin “— 0 incident(s)”.
- **Trend Micro**: extrae `sspDataInfo` desde `<script>`; agrupa por incidente, **última actualización de HOY**; mensaje combinado (Cloud One + Vision One).

---

## ➕ Añadir un nuevo vendor

1. Crea `vendors/<nombre>.py`.
2. Implementa `run()` usando `common/browser.start_driver()` y `BeautifulSoup`.
3. Mantén el formato compacto y tiempos a **UTC**.
4. Añádelo a la matriz del workflow (`status-check.yml`).
5. Opcional: exporta JSON con `--export-json` para integrarlo en el digest.

> Pautas completas en la Wiki: “Añadir un nuevo Vendor”.

---

## 🩺 Troubleshooting rápido

- **“Network is unreachable” al enviar a Telegram en CI**  
  Usa modo *preview* (`dry_run=true`) para validar el output mientras se restablece la salida a Internet del runner. Verifica `TELEGRAM_*` y `TEAMS_WEBHOOK_URL`.

- **HTML del correo “todo seguido”**  
  Ya se soluciona con `<pre class="mono" style="white-space: pre-wrap">` en la plantilla HTML.

- **Fuentes aparecen como `<li>...</li>` en TXT**  
  Usa `LISTA_FUENTES_TXT` para texto plano y `LISTA_FUENTES_CON_ENLACES` para HTML.

- **Necesito ver el DOM para ajustar selectores**  
  Ejecuta un vendor con `SAVE_HTML=1` y revisa el archivo guardado en el workspace del job.

> Más en la Wiki: “Troubleshooting & FAQ”.

---

## 📚 Documentación ampliada

Consulta la **Wiki** del repositorio:
- Instalación y puesta en marcha
- Arquitectura
- Reglas por vendor
- Plantillas & Notificaciones
- Workflow CI/CD
- Añadir un vendor
- Troubleshooting
- DORA & Seguridad

---

## 📝 Licencia

Indica aquí la licencia del proyecto (por ejemplo **MIT**). Si no has decidido una, déjalo como “All rights reserved” temporalmente.

---

## 🙌 Agradecimientos

Gracias a todas las personas que han contribuido con parsers, reglas de negocio por vendor, y mejoras de plantillas/estilos para que el informe sea útil y claro para el cliente final.
