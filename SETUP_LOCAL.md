## 🚀 SETUP RÁPIDO - Configurar para Banco Pichincha

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
CLIENT_NAME="BANCO PICHINCHA"
CLIENT_CODE="PICHINCHA"
CLIENT_FULL_NAME="Banco Pichincha - Monitoreo DORA ICT"

# Email
EMAIL_SUBJECT_PREFIX="[BANCO PICHINCHA - DORA]"
EMAIL_CONFIDENTIAL_FOOTER="Información exclusiva para uso interno Banco Pichincha"

# Contacto
CONTACT_PERSON="Equipo de Seguridad ICT"
CONTACT_DEPARTMENT="Seguridad de Información"

# URLs (opcional)
CLIENT_PORTAL_URL="https://security.pichincha.com"
CLIENT_SUPPORT_EMAIL="security@pichincha.com.ec"

# Notificaciones
NOTIFY_TO_TELEGRAM=true
NOTIFY_TO_TEAMS=true
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
| `CLIENT_NAME` | `BANCO PICHINCHA` |
| `CLIENT_CODE` | `PICHINCHA` |
| `EMAIL_CONFIDENTIAL_FOOTER` | `Información exclusiva para uso interno Banco Pichincha` |
| `CONTACT_PERSON` | `Equipo de Seguridad` |

**3. El workflow automáticamente**:
- Lee los secrets
- Genera el email con tu cliente
- Envía a Teams/Telegram

---

### ✅ Verificación de Seguridad

Ejecuta esto para confirmar que todo está privado:

```bash
# ¿El repo tiene referencias a BANCO PICHINCHA?
grep -r "BANCO PICHINCHA" . --exclude-dir=.git --exclude-dir=__pycache__
# Debe retornar SOLO archivos en .env (privado) y documentación

# ¿.env está protegido?
git status .env
# Debe mostrar: "On branch main, nothing to commit"
# (No debe aparecer en "git status" porque está en .gitignore)
```

---

### 🔐 Después de configurar

Los reportes automáticamente:
- ✅ Contienen el nombre de tu cliente (BANCO PICHINCHA)
- ✅ Pero el repositorio NO expone nada privado
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
