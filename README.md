# Web Status Monitor

Monitoriza los portales de incidentes de varios fabricantes y **envía alertas automáticas** a **Telegram** y **Microsoft Teams**.  
Diseñado con arquitectura **modular por vendor**, ejecutado de forma **orquestada** (matriz) mediante **GitHub Actions**.

---

## ✨ Funcionalidades

- **Scraping robusto** con Selenium + BeautifulSoup.
- **Netskope**: incidentes activos + “Past Incidents (Previous 15 days)”, con detección de estado (Investigating, Update, Resolved…) y fechas (inicio/fin).
- **Proofpoint**: detecta mensaje “No current identified incidents” o, si listan, solo items reales (sin navegación).
- **Qualys** (histórico por meses): **ignora** todo lo que comience por `[Scheduled]`, reporta solo incidencias reales (p. ej., “This incident has been resolved.”). Convierte horarios (PDT, etc.) → **UTC**.
- **Notificaciones** a Telegram y Microsoft Teams.
- **Workflow multi-vendor** (matriz): cada vendor se ejecuta de forma independiente.
- **Depuración opcional**: guarda el HTML renderizado (`*_page_source.html`) y lo sube como artifact del run.

---

## ✅ Estado actual

- **Netskope** (`vendors/netskope.py`)
  - Captura incidentes activos y “Past Incidents (Previous 15 days)”.
  - Evita falsos positivos (no marca como activos los “Resolved”).
  - Extrae título, estado y fechas (inicio Investigating/Identified, fin Resolved).

- **Proofpoint** (`vendors/proofpoint.py`)
  - Web simple; cuando aparece “No current identified incidents” → reporta vacío.
  - Evita enlaces de navegación (Login, Terms, Privacy, etc.).

- **Qualys** (`vendors/qualys.py`)
  - Vista histórico por meses (Agosto, Julio, Junio…).
  - **Descarta** tarjetas `[Scheduled]`.
  - Detecta incidentes reales como:
    - _All SCP Platform: VMDR Dashboard intermittently Getting "Application Crashed" - (IM-12150)_  
      _(Jun 13, 09:18 – Jun 14, 11:18 PDT → UTC)_  
    - _EU Platform 2: Scanner sync delay Issue | (IM-12123)_  
      _(Jun 2, 05:19 – 05:44 PDT → UTC)_
  - Título desde el **enlace previo a la línea de fecha**; si no existe, usa la primera línea válida.
  - Conversión de zonas horarias **a UTC** mediante mapa de abreviaturas.

---

## 📁 Estructura

```
.
├─ .github/
│  └─ workflows/
│     └─ status-check.yml        # Workflow multi-vendor (matriz)
├─ common/
│  ├─ browser.py                 # start_driver() Chrome headless
│  ├─ notify.py                  # send_telegram(), send_teams()
│  └─ format.py                  # header(), render_incidents()
├─ vendors/
│  ├─ netskope.py
│  ├─ proofpoint.py
│  └─ qualys.py
├─ run_vendor.py                 # Orquestador por vendor
├─ requirements.txt
└─ README.md
```

---

## 🔧 Requisitos

- **Python 3.10**
- Paquetes:
  - `selenium==4.20.0`
  - `beautifulsoup4`
  - `requests`
  - `lxml`
  - `python-dateutil`  ← usado por Netskope

> Asegúrate de que `requirements.txt` incluya:
```
selenium==4.20.0
requests
beautifulsoup4
lxml
python-dateutil
```

---

## 🔐 Secrets / Variables de entorno

| Nombre                | Descripción                                  |
|----------------------|----------------------------------------------|
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram                    |
| `TELEGRAM_USER_ID`   | Chat ID de Telegram                          |
| `TEAMS_WEBHOOK_URL`  | Webhook de canal de Microsoft Teams          |

**Opcional (depuración):**
- `SAVE_HTML="1"` → guarda `*_page_source.html` de cada vendor y se sube como artifact del run.

---

## ▶️ Ejecución local

1) Instala dependencias:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2) Exporta variables (ejemplo en bash):
```bash
export TELEGRAM_BOT_TOKEN=xxx
export TELEGRAM_USER_ID=123456
export TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
export SAVE_HTML=1   # opcional
```

3) Ejecuta un vendor:
```bash
python run_vendor.py --vendor netskope
python run_vendor.py --vendor proofpoint
python run_vendor.py --vendor qualys
```

---

## 🤖 GitHub Actions

Workflow: `.github/workflows/status-check.yml`  
- Ejecuta **cada hora** (cron) y manualmente (workflow_dispatch).
- Usa **matriz**: `[netskope, proofpoint, qualys]`.
- Instala Google Chrome (vía `browser-actions/setup-chrome`).
- Sube artifacts con los HTML si `SAVE_HTML=1`.

Fragmento relevante:

```yaml
strategy:
  fail-fast: false
  matrix:
    vendor: [netskope, proofpoint, qualys]

env:
  TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
  TELEGRAM_USER_ID:   ${{ secrets.TELEGRAM_USER_ID }}
  TEAMS_WEBHOOK_URL:  ${{ secrets.TEAMS_WEBHOOK_URL }}
  SAVE_HTML: "1"  # opcional para depurar

steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with: { python-version: '3.10' }
  - uses: browser-actions/setup-chrome@v1
  - name: Install dependencies
    run: |
      python -m pip install --upgrade pip
      pip install -r requirements.txt
  - name: Run ${{ matrix.vendor }}
    run: python run_vendor.py --vendor ${{ matrix.vendor }}
  - name: Upload page HTML (${{ matrix.vendor }})
    if: always()
    uses: actions/upload-artifact@v4
    with:
      name: html-${{ matrix.vendor }}
      path: |
        *page_source.html
        **/*page_source.html
      if-no-files-found: warn
      retention-days: 7
```

**Descargar artifacts**:  
Actions → ejecución → sección **Artifacts** → `html-netskope`, `html-proofpoint`, `html-qualys`.

---

## ➕ Añadir un nuevo vendor

1. Crea `vendors/<vendor>.py` con:
   - `URL` y `run()` como entrypoint.
   - Uso de `common.browser.start_driver`, `common.notify`, `common.format`.
   - Scraping/parseo específico del sitio.
2. Regístralo en `run_vendor.py`:
   ```python
   REGISTRY = {
     "netskope": "vendors.netskope",
     "proofpoint": "vendors.proofpoint",
     "qualys": "vendors.qualys",
     "<vendor>": "vendors.<vendor>",
   }
   ```
3. Añádelo a la matriz del workflow:
   ```yaml
   matrix:
     vendor: [netskope, proofpoint, qualys, <vendor>]
   ```

---

## 🧪 Ejemplos de salida

### Netskope
```
Netskope - Estado de Incidentes
2025-08-17 12:36 UTC

Incidentes activos
- No hay incidentes activos reportados.

Incidentes últimos 15 días
1. Resolved — Incident 3921093 - Service Impact to DFW1, DFW4 Data Center.
   Inicio: 2025-08-15 18:17 UTC · Fin: 2025-08-15 19:05 UTC
...
```

### Proofpoint
```
Proofpoint - Estado de Incidentes
2025-08-17 12:40 UTC

Incidentes activos
- No hay incidentes activos reportados.

Incidentes últimos 15 días
- No hay incidentes en los últimos 15 días.
```

### Qualys (histórico por meses)
```
Qualys - Estado de Incidentes
2025-08-17 12:44 UTC

Histórico (meses visibles en la página)
1. All SCP Platform: VMDR Dashboard intermittently Getting "Application Crashed" - (IM-12150)
   Estado: Resolved · Inicio: 2025-06-13 16:18 UTC · Fin: 2025-06-14 18:18 UTC
2. EU Platform 2: Scanner sync delay Issue | (IM-12123)
   Estado: Resolved · Inicio: 2025-06-02 12:19 UTC · Fin: 2025-06-02 12:44 UTC
```

---

## 🛠️ Troubleshooting

- **No aparecen artifacts `html-<vendor>`**  
  Asegúrate de tener `SAVE_HTML: "1"` en `env` del workflow y el paso `upload-artifact` al final.  
  Revisa el log del paso “Upload page HTML” para ver rutas encontradas.

- **Selenium/Chrome**  
  Usamos `browser-actions/setup-chrome@v1`. No hace falta instalar `chromedriver` manualmente.

- **Fechas/zonas horarias**  
  Qualys convierte abreviaturas (PDT, CEST, etc.) a UTC mediante un mapa (`TZ_OFFSETS_MIN`). Si aparece una nueva abreviatura, añádela al diccionario.

- **Cambios de DOM**  
  Si un vendor cambia el HTML, activa `SAVE_HTML=1`, descarga el artifact y ajusta el parser con ese HTML.

---

## 📄 Licencia

MIT (o la que corresponda).

---

## 🙌 Créditos

Proyecto de monitorización de portales de estado con envío a Telegram + Microsoft Teams.  
Arquitectura modular y workflows listos para escalar a nuevos fabricantes.
