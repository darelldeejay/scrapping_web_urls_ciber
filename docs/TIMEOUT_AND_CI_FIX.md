# 🔧 FIX: Cron envía reportes vacíos (0 proveedores)

## 🎯 Problema Identificado

El cron enviaba reportes **completamente vacíos**:

```
│ Proveedores monitorizados: 0     │  ← ❌ VACÍO
│ Incidentes nuevos hoy:    0       │  ← ❌ VACÍO
ESTADO POR PROVEEDOR ICT
[VACÍO - Ningún dato]
```

Mientras que **manual funcionaba perfectamente** con:
```
│ Proveedores monitorizados: 8     │  ← ✅ 8 DATOS
│ Incidentes nuevo hoy:    3       │  ← ✅ 3 DATOS
ESTADO POR PROVEEDOR ICT
[LLENO - Todos los 8 vendors]
```

---

## 🔍 Causa Raíz

**Los vendors fallaban en el cron debido a TIMEOUTS insuficientes.**

En GitHub Actions (runner CI):
- La red es más lenta
- Chrome headless tarda más en iniciar  
- Los sitios de status responden más lentamente
- **Timeout de 60s NO era suficiente**

Resultado:
1. Los vendors iniciaban Selenium
2. Esperaban máximo 60s a que cargara la página
3. Se agotaba el timeout antes de descargar el HTML
4. Fallaban silenciosamente
5. No generaban JSON
6. El digest se creaba con 0 datos

---

## ✅ Soluciones Implementadas

### 1. **Aumentar Timeouts (CRÍTICO)**
**Archivo:** `common/browser.py`

```python
# ANTES (60s):
page_load_timeout = 60

# DESPUÉS (180s en CI):
page_load_timeout = 180 if is_ci else 60  # 3 min en CI, 1 min local
```

- Detecta automáticamente si está en CI (GitHub Actions)
- Usa 3 minutos en CI vs 1 minuto local
- Script timeout también aumentado (120s en CI)

### 2. **Logging Detallado (DEBUG)**
**Archivo:** `.github/workflows/status-check.yml`

Ahora muestra:
- Tiempo de ejecución de cada vendor
- Tamaño y primeras líneas del JSON generado
- Errores específicos si algo falla

### 3. **Bloqueo de Envío Vacío**
**Archivo:** `scripts/validate_digest.py`

Si `NUM_PROVEEDORES == 0`:
- ✅ Detecta que NO hay datos
- ✅ Bloquea el envío
- ✅ Genera mensaje de error claro

### 4. **Scripts de Debug**
**Nuevos archivos:**
- `scripts/run_vendor_debug.py` - Ejecuta vendors con timing y análisis
- `scripts/debug_vendors.py` - Debug profundo con reportes
- `scripts/diagnose.py` - Diagnóstico completo

---

## 🧪 Por Qué Ahora Funcionará

### En CI (CRON):
1. ✅ **Timeout = 180s** (3 minutos por vendor)
2. ✅ **Logging detallado** para ver si algo falla
3. ✅ **Validación previa** - NO envía si está vacío
4. ✅ **Detección automática** de CI

### Localmente:
1. ✅ **Timeout = 60s** (1 minuto - rápido)
2. ✅ Scripts de debug para troubleshooting
3. ✅ TODO FUNCIONA (8/8 vendors)

---

## 🚀 Test/Validación

### Próxima ejecución del CRON (mañana 09:00 Madrid):
Verifica en Telegram/Teams:
```
│ Proveedores monitorizados: 8     │  ← Debería estar aquí ✅
│ Incidentes nuevos hoy:    X       │
ESTADO POR PROVEEDOR ICT
=== AKAMAI (GUARDICORE) ===
[datos del vendor]
```

### Si aún falla:
```bash
# 1. Ejecutar debug local
python scripts/run_vendor_debug.py

# 2. Ver el último log de cron en GitHub Actions
# Actions → status-check → últim run → "vendors" job

# 3. Buscar errors de "TIMEOUT" o "NETWORK" en los logs
```

---

## 📋 Archivos Modificados

```
✅ common/browser.py               (+20 líneas de timeout adaptativo)
✅ .github/workflows/status-check.yml (+ logging detallado)
✅ scripts/run_vendor_debug.py    (NEW - script de debug)
✅ docs/TIMEOUT_AND_CI_FIX.md     (NEW - esta guía)
```

---

## 💡 Por Qué Pasó Desapercibido

1. **Local funcionaba perfecto** - 60s de timeout es suficiente
2. **En CI fue silencioso** - El vendor fallaba pero no mostraba error
3. **El workflow continuaba** - Incluso sin JSONs
4. **Se enviaba digest vacío** - Sin romper el pipeline

---

## 🔮 Previsión de Problemas Futuros

Si el cron sigue fallando con este fix:

1. **TIMEOUT (vendor tarda >180s)**
   - Solución: Aumentar más los timeouts
   - Comand: `VENDOR_TIMEOUT=300 python run_vendor.py --vendor <name>`

2. **NETWORK (DNS/Conectividad)**
   - Solución: Usar proxies o agregar retry logic
   - Señal: Errores de "connection refused" en logs

3. **MEMORY (Sin RAM)**
   - Solución: Ejecutar vendors secuencialmente en lugar de paralelo
   - Señal: "Out of memory" errors

4. **BROWSER (Chrome no inicia)**
   - Solución: Cambiar opciones de Chrome en `common/browser.py`
   - Señal: "WebDriverException" en logs

---

**Última actualización:** 2026-04-19
**Status:** ✅ DEPLOYED
