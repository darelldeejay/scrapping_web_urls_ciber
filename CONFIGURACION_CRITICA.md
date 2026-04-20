# ⚠️ CONFIGURACIÓN CRÍTICA REQUERIDA

## Paso 1: Configurar `.env` local (para desarrollo/testing)

```bash
cd "c:\Users\darelldeejay\OneDrive\Gitea\Scrapping Web\repo"
cp .env.example .env
```

Editar `.env` y reemplazar valores con los de tu cliente:

```env
# Cliente - REEMPLAZAR CON TUS VALORES REALES
CLIENT_NAME="<NOMBRE_CLIENTE>"
CLIENT_CODE="<CODIGO_CLIENTE>"
CLIENT_FULL_NAME="<NOMBRE_CLIENTE> - Monitoreo DORA ICT"

# Email - PERSONALIZAR PARA TU CLIENTE
EMAIL_SUBJECT_PREFIX="[<NOMBRE_CLIENTE> - DORA]"
EMAIL_CONFIDENTIAL_FOOTER="Información exclusiva para uso interno <NOMBRE_CLIENTE>"

# Contacto - PERSONALIZAR
CONTACT_PERSON="<PERSONA_RESPONSABLE>"
CONTACT_DEPARTMENT="<DEPARTAMENTO>"

# URLs (opcional)
CLIENT_PORTAL_URL="<URL_PORTAL_CLIENTE>"
CLIENT_SUPPORT_EMAIL="<EMAIL_SOPORTE>"

# Notificaciones
NOTIFY_TO_TELEGRAM=true
NOTIFY_TO_TEAMS=true
```

**⚠️ IMPORTANTE**: Este archivo `.env` es **PRIVADO y NUNCA debe commiterse a GitHub**. Ya está en `.gitignore`.

## Paso 2: Configurar GitHub Secrets (para CI/CD)

**Ir a**: GitHub → Settings → Secrets and variables → Actions → New repository secret

Crear estos secrets (reemplazar con valores de tu cliente):

| Secret Name | Ejemplo | Notas |
|---|---|---|
| `CLIENT_NAME` | `<NOMBRE_CLIENTE>` | Nombre del cliente (mismo que en `.env`) |
| `CLIENT_CODE` | `<CODIGO_CLIENTE>` | Código interno |
| `EMAIL_CONFIDENTIAL_FOOTER` | `Información exclusiva para <NOMBRE_CLIENTE>` | Pie de página |
| `TELEGRAM_BOT_TOKEN` | `123456:ABC-DEF...` | De @BotFather en Telegram (opcional) |
| `TELEGRAM_USER_ID` | `987654321` | Tu chat ID (opcional) |
| `TEAMS_WEBHOOK_URL` | `https://outlook.webhook.office.com/...` | De Teams Webhook (opcional) |

⚠️ **NOTA CRÍTICA**: Los secrets **NUNCA se expondrán en logs** - GitHub los enmascara automáticamente. Pero deben coincidir con los valores de `.env` local.

## Paso 3: Verificar localmente

```bash
# Ver si .env está siendo leído
python -c "from common.config import get_config; cfg = get_config(); print(f'✓ {cfg.client_name}')"

# Debería mostrar: ✓ BANCO PICHINCHA
```

## Paso 4: Reejecutar workflow en GitHub Actions

1. Ir a: GitHub → Actions → `status-check` workflow
2. Click en "Run workflow"
3. Dejar opciones por defecto (CRON mode)
4. Click "Run workflow"
5. Ver logs en el job "Build & send digest"

## Troubleshooting

### ❌ Error: "ModuleNotFoundError: No module named 'common'"
✅ **SOLUCIONADO** - Se agregó sys.path fix en todos los scripts

### ❌ Error: "CLIENT_NAME is None o vacío"
**Solución**: 
- Localmente: Crear `.env` con `CLIENT_NAME="BANCO PICHINCHA"`
- En CI: Crear secret `CLIENT_NAME` en GitHub

### ❌ Error: "TELEGRAM_BOT_TOKEN not found"
**Solución**: 
- Crear secret `TELEGRAM_BOT_TOKEN` en GitHub Actions
- O desactivar en workflow: `NOTIFY_TO_TELEGRAM=false`

### ❌ Error: "TEAMS_WEBHOOK_URL not found"
**Solución**:
- Crear secret `TEAMS_WEBHOOK_URL` en GitHub Actions
- O desactivar en workflow: `NOTIFY_TO_TEAMS=false`

## Timeline

- [ ] **HOY**: Configurar `.env` local
- [ ] **HOY**: Crear GitHub Secrets (si tienes Telegram/Teams)
- [ ] **HOY**: Reejecutar workflow manualmente (test)
- [ ] **MAÑANA 09:00 Madrid**: CRON automático enviará reporte real

---

**Estado actual**: ✅ Código OK | ⏳ Configuración pendiente | ❌ Secrets no configurados
