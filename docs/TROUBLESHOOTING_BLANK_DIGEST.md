# 🔧 Troubleshooting: Cron envía información en blanco

## 📋 Problema

El workflow **programado (cron)** envía digests vacíos a Telegram/Teams, pero la **ejecución manual** funciona perfectamente.

## 🔍 Causa Raíz

Este es un patrón clásico causado por:

1. **Errores silenciados en vendors** → El `|| true` ocultaba fallos
2. **Artefactos no descargados** → Si un vendor falla, no hay JSON generado
3. **Validación insuficiente** → El digest se crea de todas formas aunque esté vacío
4. **Contexto diferente** → El cron corre en ambiente limpio, manual reutiliza caché

### Diferencias entre execución programada vs manual:

| Aspecto | Cron (programado) | Manual (dispatch) |
|--------|----------|---------|
| Ambiente | Limpio (sin cache) | Reutiliza workspace |
| Visibilidad | Logs poco detallados | Acceso a detalles |
| Errores | Se ocultan con `\|\| true` | Se ven en output |
| Artefactos | Dependen de descarga remota | Pueden estar locales |

## ✅ Soluciones Implementadas

### 1. **Mejor manejo de errores en vendors**

**Antes:**
```yaml
python run_vendor.py --vendor ${{ matrix.vendor }} --export-json "..." || true
```

**Después:**
```yaml
- name: Export ${{ matrix.vendor }} to JSON (no notify)
  id: export
  run: |
    if python run_vendor.py --vendor ${{ matrix.vendor }} --export-json "..."; then
      echo "✅ Completado"
    else
      echo "❌ Error"
      exit 1  # Detiene la ejecución, NO oculta el error
    fi
```

### 2. **Validación de JSONs creados**

```yaml
- name: Verify JSON was created
  run: |
    FILE=".github/out/vendors/${{ matrix.vendor }}.json"
    if [ -f "$FILE" ]; then
      SIZE=$(stat -c%s "$FILE" 2>/dev/null || ...)
      echo "✅ JSON: $FILE ($SIZE bytes)"
    else
      echo "❌ ERROR: No se creó $FILE"
      exit 1
    fi
```

### 3. **Verificación de artefactos en digest**

```yaml
- name: Verify downloaded artifacts
  run: |
    COUNT=$(find .github/out/vendors -name "*.json" 2>/dev/null | wc -l)
    if [ "$COUNT" -eq 0 ]; then
      echo "⚠️ ADVERTENCIA: No hay JSONs"
    fi
```

### 4. **Validación de digest_data.json**

```yaml
- name: Validate digest data
  id: validate
  run: |
    if [ ! -f ".github/out/digest_data.json" ]; then
      exit 1
    fi
    SIZE=$(stat -c%s ".github/out/digest_data.json")
    if [ "$SIZE" -lt 50 ]; then
      echo "❌ digest_data.json está vacío"
      exit 1
    fi
```

### 5. **Script de diagnóstico local**

Nuevo script: [`scripts/diagnose.py`](../scripts/diagnose.py)

```bash
python scripts/diagnose.py
```

Salida:
```
▶️  NETSKOPE
   Ejecutando: ...
   ✅ OK (2847 bytes)

▶️  PROOFPOINT
   ✅ OK (523 bytes)

...

📊 RESUMEN
✅ OK:        8/8
```

## 🚀 Cómo debuggear ahora

### Paso 1: Verificar localmente que los vendors funcionan

```bash
cd repo/
python scripts/diagnose.py
```

**Resultado esperado:**
```
✅ OK:        8/8
```

**Si hay fallos:**
- El script te indicará cuál vendor falla
- Revisa el vendor específico:
  ```bash
  SAVE_HTML=1 python run_vendor.py --vendor netskope --export-json test.json
  ```

### Paso 2: Verificar el workflow en GitHub

1. Ve a **Actions** → **status-check**
2. Click en **Run workflow** → **Run workflow**
3. Selecciona:
   - `send_channels`: `none`
   - `dry_run`: `true` (solo preview, no envía)
4. Espera a que termine
5. Descarga el artifact `digest-preview`
6. Verifica los archivos:
   - `subject.txt` → asunto (¿está vacío?)
   - `text_body.txt` → cuerpo (¿tiene datos?)
   - `digest_data.json` → datos (¿tiene contenido?)

### Paso 3: Revisar logs del workflow

En la ejecución de GitHub Actions:

1. **Job vendors**: Expande cada vendor, verifica ✅ OK
2. **Job digest**: Expande "Verify downloaded artifacts" y "Validate digest data"
3. Si ves ⚠️ ADVERTENCIA o ❌ ERROR, ese es el problema

## 📝 Checklist rápido

Antes de volver a ejecutar el cron:

- [ ] ¿Ejecutaste `diagnose.py` localmente? ¿Todos OK?
- [ ] ¿Verificaste que los secrets están en GitHub? (TELEGRAM_BOT_TOKEN, TEAMS_WEBHOOK_URL)
- [ ] ¿Hiciste un test manual del workflow con `dry_run=true`?
- [ ] ¿Descargaste los artifacts y verificaste que no están vacíos?
- [ ] ¿Revisaste si algún vendor cambió su DOM? (check `SAVE_HTML=1`)

## 🛠️ Comandos útiles

```bash
# Ejecutar diagnóstico
python scripts/diagnose.py

# Ejecutar un vendor específico y guardar HTML
SAVE_HTML=1 python run_vendor.py --vendor netskope --export-json test.json

# Ver el JSON generado
cat test.json | python -m json.tool | head -20

# Limpiar y empezar de cero
rm -rf .github/out/

# Construir digest localmente (preview, sin enviar)
NOTIFY_DRY_RUN=true python run_digest.py \
  --text-template templates/dora_email.txt \
  --html-template templates/dora_email.html \
  --data .github/out/digest_data.json \
  --channels both \
  --preview-out .github/out/preview
```

## 🎯 Próximos pasos

1. Copia el archivo `status-check.yml` mejorado a tu repo
2. Ejecuta `python scripts/diagnose.py` localmente
3. Haz un test manual del workflow
4. Confirma que el cron funciona en la próxima ejecución programada

Si el problema persiste, revisa:
- **Selectores CSS en vendors**: El sitio de status pudo cambiar su HTML
- **Timeouts**: Chrome tarda más de lo esperado en cargar
- **Autenticación**: Algunos sitios requieren verificación adicional

---

**Última actualización**: 2026-04-19
**Cambios**: Mejor error handling, validación de datos, script diagnóstico
