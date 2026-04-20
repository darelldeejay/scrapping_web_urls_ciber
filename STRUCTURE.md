# 📁 Estructura del Proyecto

Organización profesional del repositorio `scrapping_web_urls_ciber`.

## Directorios Principales

### `scripts/`
Scripts ejecutables que orquestan el flujo de trabajo:
- **`run_vendor.py`** — Scraping de un vendor específico, exporta JSON
- **`run_digest.py`** — Compila digest y envía notificaciones (Teams/Telegram)
- **`build_digest.py`** — (Legacy) Construcción de digest
- **`build_digest_data.py`** — Compila datos de vendors en estructura unificada
- **`validate_digest.py`** — Valida integridad del digest
- **`diagnose.py`** — Diagnóstico de problemas
- **`debug_vendors.py`** — Debug detallado de vendors
- **`run_vendor_debug.py`** — Debug con captura de HTML

### `common/`
Módulos reutilizables compartidos:
- **`browser.py`** — Selenium WebDriver con timeouts adaptativos (180s CI / 60s local)
- **`digest_export.py`** — Exportación de datos
- **`format.py`** — Formatos y transformaciones
- **`notify.py`** — Notificaciones (Teams, Telegram)
- **`statuspage.py`** — Integración con statuspage
- **`templates.py`** — Procesamiento de templates
- **`fallback_collectors.py`** — Collectors alternativos

### `vendors/`
Implementaciones de scraping por vendor:
- **`aruba.py`**, **`cyberark.py`**, **`guardicore.py`**
- **`imperva.py`**, **`netskope.py`**, **`proofpoint.py`**
- **`qualys.py`**, **`trendmicro.py` (trend_vision_one.py, trend_cloud_one.py)**

### `templates/`
Templates de email (notificaciones):
- **`dora_email.txt`** — Versión texto plano
- **`dora_email.html`** — Versión HTML

### `.github/workflows/`
Workflows de CI/CD:
- **`status-check.yml`** — Orquesta scraping, compilación y notificaciones
  - Triggers: Manual (`workflow_dispatch`) + CRON diario (09:00 Madrid)
  - Matrix: 8 vendors paralelos
  - Timeout CI: 180s por vendor (adaptativo)

### `.github/out/` (generado, ignorado)
Salida del workflow:
- **`vendors/*.json`** — JSONs de cada vendor
- **`digest_data.json`** — Datos compilados
- **`preview/`** — Previsualizaciones de email (solo en dry-run)

### `docs/`
Documentación técnica y troubleshooting

## Convención de Naming

| Tipo | Patrón | Ejemplo | Ubicación |
|------|--------|---------|-----------|
| Script ejecutable | `run_*.py`, `build_*.py` | `run_vendor.py` | `scripts/` |
| Módulo compartido | `*.py` | `browser.py` | `common/` |
| Vendor impl. | `{vendor}.py` | `aruba.py` | `vendors/` |
| Template | `*.{txt,html}` | `dora_email.txt` | `templates/` |
| Config workflow | `*.yml` | `status-check.yml` | `.github/workflows/` |

## Flujo de Ejecución

```
CRON (09:00 Madrid)
    ↓
Workflow: status-check.yml
    ├─→ Job: vendors (matrix 8 vendors)
    │   ├─→ run_vendor.py --vendor <name> --export-json
    │   └─→ Output: .github/out/vendors/{vendor}.json
    │
    └─→ Job: digest (depende de vendors)
        ├─→ build_digest_data.py (compilar JSONs)
        ├─→ validate_digest.py (verificar integridad)
        ├─→ run_digest.py (enviar notificaciones)
        └─→ Output: Email a Teams + Telegram
```

## Uso Local

```bash
# Scraping de un vendor
python scripts/run_vendor.py --vendor aruba --export-json .github/out/vendors/aruba.json

# Debug con captura HTML
SAVE_HTML=1 python scripts/run_vendor.py --vendor aruba

# Validación
python scripts/validate_digest.py --data .github/out/digest_data.json

# Diagnóstico
python scripts/diagnose.py
```

## Cambios Recientes

- ✅ **Organización**: Todos los scripts movidos a `scripts/` (antes dispersos en raíz)
- ✅ **Timeouts adaptativos**: 180s en CI, 60s localmente (en `common/browser.py`)
- ✅ **Limpieza**: Archivos de debug en `.gitignore` (HTMLs, JSONs)
- ✅ **Workflow updated**: Rutas consistentes con `scripts/` prefix

## Próximos Pasos

- [ ] Considerar module docstrings en cada script
- [ ] Agregar type hints a funciones clave
- [ ] Documentar variables de ambiente necesarias
