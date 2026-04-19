#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🔍 Script de diagnóstico para verificar si los vendors funcionan.
Útil para debugging cuando el cron envía información en blanco.

Uso:
    python scripts/diagnose.py
    
Salida:
    - Estado de cada vendor (✅ OK, ❌ FAIL)
    - Tamaño de JSON generado
    - Primeras líneas de datos
    - Recomendaciones de fix
"""

import os
import sys
import json
import glob
import subprocess
import tempfile
from datetime import datetime

def run_vendor(vendor_name: str, tmpdir: str) -> dict:
    """Ejecuta un vendor y retorna status."""
    out_file = os.path.join(tmpdir, f"{vendor_name}.json")
    cmd = [
        sys.executable, "run_vendor.py",
        "--vendor", vendor_name,
        "--export-json", out_file
    ]
    
    print(f"\n▶️  {vendor_name.upper()}")
    print(f"   Ejecutando: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            print(f"   ❌ FAIL (código {result.returncode})")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
            return {"vendor": vendor_name, "status": "FAIL", "reason": "Exit code != 0", "size": 0}
        
        if not os.path.exists(out_file):
            print(f"   ❌ FAIL (JSON no creado)")
            return {"vendor": vendor_name, "status": "FAIL", "reason": "JSON no creado", "size": 0}
        
        size = os.path.getsize(out_file)
        if size < 50:
            print(f"   ⚠️  SMALL ({size} bytes)")
            with open(out_file, "r") as f:
                content = f.read()
            print(f"   Contenido: {content[:100]}")
            return {"vendor": vendor_name, "status": "SMALL", "size": size, "reason": "JSON muy pequeño"}
        
        with open(out_file, "r") as f:
            data = json.load(f)
        
        # Validar estructura mínima
        if not isinstance(data, dict):
            print(f"   ❌ INVALID (no es dict)")
            return {"vendor": vendor_name, "status": "INVALID", "reason": "Resultado no es dict", "size": size}
        
        print(f"   ✅ OK ({size} bytes)")
        return {"vendor": vendor_name, "status": "OK", "size": size, "data": data}
        
    except subprocess.TimeoutExpired:
        print(f"   ⏱️  TIMEOUT (>60s)")
        return {"vendor": vendor_name, "status": "TIMEOUT", "reason": "Timeout", "size": 0}
    except Exception as e:
        print(f"   ❌ ERROR: {str(e)[:100]}")
        return {"vendor": vendor_name, "status": "ERROR", "reason": str(e)[:100], "size": 0}

def main():
    vendors = ["netskope", "proofpoint", "qualys", "aruba", "imperva", "cyberark", "trendmicro", "guardicore"]
    
    print("=" * 70)
    print("🔍 DIAGNÓSTICO DE VENDORS")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Vendors a revisar: {len(vendors)}")
    print()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        results = []
        for vendor in vendors:
            result = run_vendor(vendor, tmpdir)
            results.append(result)
    
    # Resumen
    print("\n" + "=" * 70)
    print("📊 RESUMEN")
    print("=" * 70)
    
    ok_count = sum(1 for r in results if r["status"] == "OK")
    fail_count = sum(1 for r in results if r["status"] in ("FAIL", "ERROR", "TIMEOUT", "INVALID"))
    small_count = sum(1 for r in results if r["status"] == "SMALL")
    
    print(f"\n✅ OK:        {ok_count}/{len(vendors)}")
    print(f"❌ FAILED:    {fail_count}/{len(vendors)}")
    print(f"⚠️  SMALL:    {small_count}/{len(vendors)}")
    
    # Detalles de fallos
    if fail_count > 0 or small_count > 0:
        print(f"\n🚨 VENDORS CON PROBLEMAS:\n")
        for r in results:
            if r["status"] != "OK":
                print(f"  • {r['vendor'].upper()}: {r['status']}")
                print(f"    Razón: {r.get('reason', 'Unknown')}")
                print()
    
    # Recomendaciones
    print("💡 RECOMENDACIONES:")
    print()
    if fail_count > 0:
        print("1. Revisa los vendores fallidos:")
        print("   - ¿El sitio de status está accesible?")
        print("   - ¿El DOM ha cambiado?")
        print("   - ¿Hay problema de permisos/firewall?")
        print()
    if small_count > 0:
        print("2. Los JSONs pequeños pueden ser:")
        print("   - Datos realmente vacíos (OK)")
        print("   - Parsers incompletos")
        print("   - Errores silenciados")
        print()
    if ok_count == len(vendors):
        print("✅ Todos los vendors funcionan. El problema está en el digest o permisos.")
        print()
        print("Próximos pasos:")
        print("  1. Ejecuta localmente: python run_digest.py --help")
        print("  2. Verifica los secrets en GitHub: TELEGRAM_BOT_TOKEN, TEAMS_WEBHOOK_URL")
        print("  3. Ejecuta un test manual del workflow en GitHub Actions")
    
    print("\n" + "=" * 70)
    
    # Exit code
    sys.exit(0 if (fail_count == 0 and small_count == 0) else 1)

if __name__ == "__main__":
    main()
