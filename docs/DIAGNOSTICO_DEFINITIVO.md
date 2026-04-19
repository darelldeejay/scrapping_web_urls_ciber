# 🔍 GUÍA DEFINITIVA: Por qué Cron → Vacío, Manual → OK

## Paso 1: Verificar exactamente CÓMO ejecutas "manual"

¿Eres hacer esto?

### ❓ Opción A: Manual EN GitHub Actions
```
1. Ve a GitHub → Actions → status-check
2. Click "Run workflow"
3. Selecciona: send_channels=both, dry_run=false
4. Esperas que termine
5. Revistas que llegó a Telegram/Teams
```

**Si esto funciona**, el problema está en el **CRON**, no en el workflow.

### ❓ Opción B: Todo LOCAL, luego GitHub solo recibe
```
1. Ejecutas localmente: python run_vendor.py --vendor netskope ...
2. Ejecutas localmente: python run_digest.py ...
3. El resultado ya está en Telegram/Teams
4. El cron también lo hace, pero falla en el paso de envío
```

**Si esto es así**, el problema es que **los JSONs no se generan en el cron**.

---

## Paso 2: Test definitivo para saber qué está pasando

### 🔴 Test Rojo: Ejecutar CRON ahora

1. Ve a **GitHub → Actions → status-check**
2. **Busca la última ejecución del CRON** (la que envió vacío)
3. Abre el artifact `digest-preview` (si exists)
4. Verifica: ¿`digest_data.json` está vacío o tiene datos?

**Si tiene datos**: El problema está en la plantilla o envío  
**Si está vacío**: Los vendors NO generaron JSONs

### 🟢 Test Verde: Ejecutar MANUAL ahora

1. Ve a **GitHub → Actions → status-check**
2. Click **"Run workflow"**
3. Selecciona:
   - `send_channels`: `none`  
   - `dry_run`: `true`
4. Espera a que termine
5. Descarga artifact `digest-preview`
6. Abre `digest_data.json`: **¿Tiene datos o está vacío?**

**Si tiene datos**: El workflow funciona, problema es el cron  
**Si está vacío**: El workflow SIEMPRE genera digest vacío

---

## Paso 3: El verdadero culpable

### Escenario 1: Manual OK, Cron vacío

**Causa probable**: Los JSONs no se descargan en el cron

```yaml
# En el workflow, el job digest depende de vendors
# Si vendors falla, los artefactos no existen
# Pero continue-on-error: true lo oculta
```

**Solución**: Ver por qué los vendors FALLAN en cron

### Escenario 2: Manual también vacío

**Causa probable**: El problema está en cómo se usan los datos

```yaml
# build_digest_data.py: Si no hay JSONs, crea datos vacíos
# run_digest.py: Renderiza plantillas con datos vacíos
# Result: Envía reporte en blanco
```

**Solución**: Agregamos validación que BLOQUEA envios vacíos

---

## Paso 4: Comandos para investigar

### Ejecutar debug completo LOCALMENTE

```bash
# Descarga el repo
cd repo/

# 1) ¿Los vendors funcionan?
python scripts/diagnose.py

# 2) ¿Qué contiene cada JSON?
ls -lah .github/out/vendors/
cat .github/out/vendors/netskope.json | python -m json.tool | head -20

# 3) ¿El digest se construye?
python scripts/build_digest_data.py \
  --vendors-dir .github/out/vendors \
  --out .github/out/digest_data.json

# 4) ¿Es válido?
python scripts/validate_digest.py --data .github/out/digest_data.json

# 5) Debug profundo
python scripts/debug_vendors.py
# Verifica: .github/out/vendor_debug_report.md
```

### Leer el output del CRON en GitHub

1. Ve a **Actions → status-check → última ejecución del cron**
2. Abre **job "vendors"**
3. Expande cada vendor (netskope, proofpoint, etc)
4. ¿Ves ✅ OK o ❌ ERROR?
5. Si ves ❌ ERROR, ese es el problema

5. Abre **job "digest"**
6. Expande **"Verify downloaded artifacts"**
7. ¿Dice "0 JSON encontrados"?
8. Si sí, los vendors FALLARON

---

## Paso 5: Las 3 posibles soluciones

### 🛠️ Solución 1: Los vendors fallan por DOM cambió

```bash
SAVE_HTML=1 python run_vendor.py --vendor netskope --export-json test.json
# Abre el HTML guardado y verifica los selectores
# Compara con versiones anteriores
```

### 🛠️ Solución 2: Timeout o conexión lenta

Aumentar timeout en `common/browser.py`:
```python
# De: timeout=10
# A: timeout=20  # Selenium espera más tiempo
```

### 🛠️ Solución 3: El sitio tiene protección (CloudFlare, etc)

Agregar user-agent real:
```python
options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
```

---

## ✅ Checklist de Acción

- [ ] **Identifica cómo ejecutas "manual"** (Opción A o B?)
- [ ] **Ejecuta Test Rojo** (última ejecución cron)
- [ ] **Ejecuta Test Verde** (manual ahora)
- [ ] **Compara `digest_data.json`** en ambos
- [ ] **Si están vacío**: Ejecuta `python scripts/diagnose.py`
- [ ] **Si diagnose falla**: Revisa vendors específicos
- [ ] **Si diagnose OK**: El problema está en cron (permisos, timeout, etc)

---

## 📞 Información que necesito para ayudarte

Cuando me respondas, por favor:

1. **¿Cómo ejecutas manual?** (Opción A, B, u otra)
2. **Última ejecución CRON**:
   - ¿Cuándo fue? (ej: 2026-04-19 09:00)
   - ¿Artifact `digest-preview` existe?
   - Si existe, ¿qué contiene `digest_data.json`?
3. **Ejecuta ahora** `python scripts/diagnose.py` localmente
   - ¿Resultado?
   - ¿Todos OK o hay fallos?

Con eso identifico exactamente el problema. 🎯
