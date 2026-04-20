#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Wrapper mejorado para run_vendor.py que captura logs detallados.
Útil para debuggear por qué los vendors fallan en CI.

Uso:
    python run_vendor_debug.py --vendor netskope --export-json out.json

Salida:
    - Logs detallados de timing
    - Capturas de errores
    - Reporte de qué salió mal
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime
from pathlib import Path

# Force UTF-8 encoding for stdout on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def run_vendor_with_debug(vendor_name: str, export_json: str = None) -> dict:
    """Ejecuta un vendor con logging detallado y captura de errores."""
    
    report = {
        "vendor": vendor_name,
        "timestamp": datetime.now().isoformat(),
        "status": "UNKNOWN",
        "timing": {},
        "output": "",
        "errors": "",
    }
    
    # Preparar environment con debug
    env = os.environ.copy()
    env["DEBUG"] = "1"
    env["VENDOR_TIMEOUT"] = "120"  # 2 minutos por vendor
    
    # Construir ruta relativa al script actual
    script_dir = os.path.dirname(os.path.abspath(__file__))
    run_vendor_path = os.path.join(script_dir, "run_vendor.py")
    
    cmd = [sys.executable, run_vendor_path, "--vendor", vendor_name]
    if export_json:
        cmd.extend(["--export-json", export_json])
    
    print(f"\n{'='*70}")
    print(f"🔍 Ejecutando: {' '.join(cmd)}")
    print(f"{'='*70}")
    
    start = time.time()
    report["timing"]["start"] = start
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=150,  # 2.5 min timeout total
            env=env
        )
        
        elapsed = time.time() - start
        report["timing"]["elapsed_sec"] = elapsed
        report["exit_code"] = result.returncode
        report["output"] = result.stdout[:1000] if result.stdout else ""
        report["errors"] = result.stderr[:1000] if result.stderr else ""
        
        # Análisis del resultado
        if result.returncode != 0:
            report["status"] = "FAILED"
            print(f"❌ FAILED (exit code {result.returncode})")
            if "TimeoutException" in result.stderr or "timeout" in result.stderr.lower():
                report["failure_reason"] = "TIMEOUT - Selenium esperó demasiado"
            elif "Network" in result.stderr or "connection" in result.stderr.lower():
                report["failure_reason"] = "NETWORK - No pudo conectar al sitio"
            elif "Memory" in result.stderr:
                report["failure_reason"] = "MEMORY - Sin memoria disponible"
            else:
                report["failure_reason"] = "UNKNOWN - Ver stderr"
        else:
            # Verificar que el JSON se creó
            if export_json and os.path.exists(export_json):
                size = os.path.getsize(export_json)
                if size < 50:
                    report["status"] = "EMPTY"
                    report["failure_reason"] = f"JSON vacío ({size} bytes)"
                    print(f"⚠️  JSON vacío ({size} bytes)")
                else:
                    report["status"] = "OK"
                    report["json_size"] = size
                    print(f"✅ OK ({elapsed:.1f}s, {size} bytes)")
            else:
                report["status"] = "NO_JSON"
                report["failure_reason"] = "JSON no creado"
                print(f"❌ JSON no creado")
        
        # Log de timing
        if elapsed > 60:
            print(f"⚠️  LENTO: {elapsed:.1f}s (>60s podría ser timeout en CI)")
        
        if result.stderr:
            print(f"\n📋 STDERR (primeras líneas):")
            print("\n".join(result.stderr.split("\n")[:10]))
        
    except subprocess.TimeoutExpired:
        report["status"] = "TIMEOUT"
        report["timing"]["elapsed_sec"] = 150
        report["failure_reason"] = "Subprocess timeout (>150s)"
        print(f"⏱️  TIMEOUT: Proceso tardó >150s")
    except Exception as e:
        report["status"] = "ERROR"
        report["failure_reason"] = str(e)
        print(f"💥 ERROR: {str(e)}")
    
    return report

def main():
    """Ejecuta todos los vendors con debug."""
    vendors = ["netskope", "proofpoint", "qualys", "aruba", "imperva", "cyberark", "trendmicro", "guardicore"]
    
    print(f"\n{'='*70}")
    print("🔍 EJECUCIÓN COMPLETA DE VENDORS CON DEBUG")
    print(f"{'='*70}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Vendors: {', '.join(vendors)}")
    
    os.makedirs(".github/out/vendors", exist_ok=True)
    
    reports = []
    for vendor in vendors:
        out_file = f".github/out/vendors/{vendor}.json"
        report = run_vendor_with_debug(vendor, export_json=out_file)
        reports.append(report)
    
    # Resumen
    print(f"\n{'='*70}")
    print("📊 RESUMEN")
    print(f"{'='*70}")
    
    ok = sum(1 for r in reports if r["status"] == "OK")
    failed = sum(1 for r in reports if r["status"] != "OK")
    total_time = sum(r.get("timing", {}).get("elapsed_sec", 0) for r in reports)
    
    print(f"\n✅ OK:         {ok}/{len(vendors)}")
    print(f"❌ FAILED:     {failed}/{len(vendors)}")
    print(f"⏱️  Total time: {total_time:.1f}s")
    
    # Detalle de fallos
    if failed > 0:
        print(f"\n🚨 FALLOS DETECTADOS:\n")
        for r in reports:
            if r["status"] != "OK":
                print(f"  • {r['vendor'].upper()}: {r['status']}")
                print(f"    Razón: {r.get('failure_reason', 'Unknown')}")
                if r.get("timing", {}).get("elapsed_sec", 0) > 60:
                    print(f"    ⚠️  Tiempo: {r['timing']['elapsed_sec']:.1f}s (LENTO)")
    
    # Guardar reporte JSON
    report_file = ".github/out/vendor_run_debug.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, ensure_ascii=False)
    print(f"\n📄 Reporte: {report_file}")
    
    # Recomendaciones
    if failed > 0:
        print(f"\n💡 RECOMENDACIONES:\n")
        timeouts = [r for r in reports if "TIMEOUT" in r.get("failure_reason", "")]
        networks = [r for r in reports if "NETWORK" in r.get("failure_reason", "")]
        
        if timeouts:
            print(f"  • TIMEOUT({len(timeouts)}): Aumentar timeouts en common/browser.py")
            print(f"    - Cambiar: page_load_timeout=60 → 120")
            print(f"    - Cambiar: set_script_timeout(30) → 60")
        
        if networks:
            print(f"  • NETWORK({len(networks)}): Problema de conectividad")
            print(f"    - Verificar DNS en el runner")
            print(f"    - Agregar retry logic")
            print(f"    - Usar proxies si aplica")
        
        print(f"\n  • Ejecutar localmente: python run_vendor_debug.py --vendor <name>")
    else:
        print(f"\n✅ Todos los vendors funcionan correctamente")
    
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
