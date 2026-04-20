## 🚀 SETUP RÁPIDO - Configurar para tu Cliente

### ⚡ En tu máquina (desarrollo local)

```bash
# Paso 1: Copiar template de configuración
cp .env.example .env

# Paso 2: Editar .env con tus datos (no se comitea a GitHub)
nano .env  # o usa tu editor favorito
```

Contenido de `.env` (PRIVADO - NUNCA COMMITEAR):
```env
# Información del cliente
# ⚠️ IMPORTANTE: Reemplaza <CLIENTE> con tu cliente real
# Este archivo NUNCA se commitea a GitHub

CLIENT_NAME="<NOMBRE_CLIENTE>"
CLIENT_CODE="<CÓDIGO_CLIENTE>"
CLIENT_FULL_NAME="<CLIENTE> - Monitoreo DORA ICT"

# Email
EMAIL_SUBJECT_PREFIX="[<NOMBRE_CLIENTE> - DORA]"
EMAIL_CONFIDENTIAL_FOOTER="Información exclusiva para uso interno <NOMBRE_CLIENTE>"

# Contacto
CONTACT_PERSON="Equipo de Seguridad ICT"
CONTACT_DEPARTMENT="Seguridad de Información"

# URLs (opcional)
CLIENT_PORTAL_URL="https://security.<cliente>.com"
CLIENT_SUPPORT_EMAIL="security@<cliente>.com"

# Notificaciones
NOTIFY_TO_TELEGRAM=true
NOTIFY_TO_TEAMS=true
```

**Ejemplo de configuración (PRIVADA en tu máquina):**
```
CLIENT_NAME="TU_CLIENTE_AQUÍ"
CLIENT_CODE="TU_CÓDIGO_AQUÍ"
```

Paso 3: Verificar que funciona
```bash
python -c "from common.config import get_config; c = get_config(); print(f'✅ Configurado para: {c.client_name}')"
```

---

### 🔄 En GitHub (producción automática - CRON diario 09:00 Madrid)

Para que el CRON tome tus datos privados, usa GitHub Secrets:

**1. Ir a**: `Settings → Secrets and variables → Actions`

**2. Crear estos secrets** (botón "New repository secret"):

| Secret Name | Value |
|-------------|-------|
| `CLIENT_NAME` | `<TU_CLIENTE>` |
| `CLIENT_CODE` | `<CÓDIGO_CLIENTE>` |
| `EMAIL_CONFIDENTIAL_FOOTER` | `Información exclusiva para <TU_CLIENTE>` |
| `CONTACT_PERSON` | `Equipo de Seguridad` |

**⚠️ IMPORTANTE**: Los valores son EJEMPLOS. Reemplaza con tu cliente real.

**3. El workflow automáticamente**:
- Lee los secrets desde GitHub
- Genera el email con tu cliente
- Envía a Teams/Telegram
- Los valores NUNCA aparecen en logs

---

### ✅ Verificación de Seguridad

Ejecuta esto para confirmar que todo está privado:

```bash
# ¿El repo tiene referencias públicas a tu cliente?
# Nota: Solo debe haber referencias en .env (privado)
grep -r "TU_CLIENTE" . --exclude-dir=.git --exclude-dir=__pycache__
# No debe retornar NADA (porque TU_CLIENTE está solo en .env privado)

# ¿.env está protegido?
git status .env
# Debe mostrar: "On branch main, nothing to commit"
# (No debe aparecer en "git status" porque está en .gitignore)
```

---

### 🔐 Después de configurar

Los reportes automáticamente:
- ✅ Contienen el nombre de tu cliente (desde .env privado)
- ✅ Pero el repositorio NO expone nada privado en GitHub
- ✅ Son reutilizables para otros clientes (solo cambiar .env)

---

### 📝 Para otro cliente en el futuro

```bash
# Si quieres usar el repo para OTRO cliente, solo:
cp .env.example .env
# Editar .env con datos del nuevo cliente

# El workflow se adaptará automáticamente
```

---

### ❓ Dudas?

Ver: `docs/PRIVATE_CONFIG.md` para documentación completa.
