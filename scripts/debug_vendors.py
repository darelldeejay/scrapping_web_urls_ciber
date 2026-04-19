#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ejecuta todos los vendors con DEBUG detallado y genera reporte diagnóstico.

Útil para entender POR QUÉ los vendors fallan en cron:
- Timeouts
- Cambios de DOM
- Errores de conexión
- Datos vacíos

Uso:
    python scripts/debug_vendors.py
    
Genera:
    .github/out/vendor_debug_report.md  → Reporte detallado
    .github/out/vendor_debug_report.json → Datos estructurados
"""

import os
import sys
import json
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, List, Any

def run_vendor_with_debug(vendor_name: str, tmpdir: str) -> Dict[str, Any]:
    """Ejecuta vendor con capturas de debug."""
    
    out_file = os.path.join(tmpdir, f"{vendor_name}.json")
    html_file = os.path.join(tmpdir, f"{vendor_name}.html")
    
    env = os.environ.copy()
    env["SAVE_HTML"] = "1"  # Guarda HTML para análisis
    env["DEBUG"] = "1"       # Activa debug si existe
    
    cmd = [
        sys.executable, "run_vendor.py",
        "--vendor", vendor_name,
        "--export-json", out_file
    ]
    
    start_time = datetime.now()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env
    )
    elapsed = (datetime.now() - start_time).total_seconds()
    
    # Resultado
    report = {
        "vendor": vendor_name,
        "status": "UNKNOWN",
        "elapsed_sec": elapsed,
        "exit_code": result.returncode,
        "stdout": result.stdout[:500] if result.stdout else "",
        "stderr": result.stderr[:500] if result.stderr else "",
        "json_created": os.path.exists(out_file),
        "html_created": os.path.exists(html_file),
        "json_size": os.path.getsize(out_file) if os.path.exists(out_file) else 0,
        "html_size": os.path.getsize(html_file) if os.path.exists(html_file) else 0,
    }
    
    # Intentar leer JSON
    if os.path.exists(out_file):
        try:
            with open(out_file, "r") as f:
                data = json.load(f)
            report["json_valid"] = True
            report["json_keys"] = list(data.keys())
            report["has_incidents"] = bool(data.get("incidents_lines"))
            report["has_components"] = bool(data.get("component_lines"))
        except:
            report["json_valid"] = False
    
    # Determinar status
    if result.returncode != 0:
        report["status"] = "FAILED"
        report["reason"] = "Exit code != 0"
    elif not report["json_created"]:
        report["status"] = "FAILED"
        report["reason"] = "JSON not created"
    elif report["json_size"] < 50:
        report["status"] = "FAILED"
        report["reason"] = f"JSON too small ({report['json_size']} bytes)"
    elif not report.get("json_valid"):
        report["status"] = "FAILED"
        report["reason"] = "Invalid JSON"
    else:
        report["status"] = "OK"
    
    return report

def format_report_md(reports: List[Dict[str, Any]]) -> str:
    """Formatea reporte en Markdown."""
    
    lines = [
        "# 🔍 Debug Report de Vendors",
        f"**Generado**: {datetime.now().isoformat()}",
        "",
        "## 📊 Resumen",
        "",
    ]
    
    ok_count = sum(1 for r in reports if r["status"] == "OK")
    fail_count = sum(1 for r in reports if r["status"] == "FAILED")
    
    lines.extend([
        f"- ✅ OK: {ok_count}",
        f"- ❌ FAILED: {fail_count}",
        f"- Total: {len(reports)}",
        "",
        "## 📋 Detalle por Vendor",
        "",
    ])
    
    for r in reports:
        icon = "✅" if r["status"] == "OK" else "❌"
        lines.append(f"### {icon} {r['vendor'].upper()}")
        lines.extend([
            f"- **Status**: {r['status']}",
            f"- **Exit Code**: {r['exit_code']}",
            f"- **Tiempo**: {r['elapsed_sec']:.1f}s",
            f"- **JSON**: {r['json_size']} bytes" + (" ✅" if r['json_created'] else " ❌"),
            f"- **HTML**: {r['html_size']} bytes" + (" ✅" if r['html_created'] else " ❌"),
        ])
        
        if r["status"] == "FAILED":
            lines.extend([
                f"- **Razón**: {r.get('reason', 'Unknown')}",
                f"- **Error**: `{r['stderr'][:200] if r['stderr'] else 'N/A'}`",
            ])
        else:
            lines.extend([
                f"- **JSON válido**: {'✅' if r.get('json_valid') else '❌'}",
                f"- **Tiene incidentes**: {'✅' if r.get('has_incidents') else '❌'}",
                f"- **Tiene componentes**: {'✅' if r.get('has_components') else '❌'}",
            ])
        
        lines.append("")
    
    # Recomendaciones
    failed = [r for r in reports if r["status"] == "FAILED"]
    if failed:
        lines.extend([
            "## 💡 Recomendaciones",
            "",
        ])
        
        for r in failed:
            lines.append(f"### {r['vendor'].upper()}")
            
            if r['exit_code'] != 0:
                lines.append("1. **Exit code != 0**: Ejecutar localmente para ver el error completo")
                lines.append(f"   ```bash")
                lines.append(f"   SAVE_HTML=1 python run_vendor.py --vendor {r['vendor']} --export-json test.json")
                lines.append(f"   ```")
            
            if r['json_size'] < 50:
                lines.append("2. **JSON muy pequeño**: El scraping devolvió datos vacíos")
                lines.append("   - Verificar si el sitio de status está UP")
                lines.append("   - Revisar si el DOM del sitio cambió (check HTML guardado)")
            
            if r.get('html_created') and r['html_size'] > 100:
                lines.append(f"3. **HTML generado**: Revisar en `.github/out/vendors/{r['vendor']}.html`")
                lines.append("   - Buscar el selector CSS esperado")
                lines.append("   - Comparar con versión anterior")
            
            lines.append("")
    
    return "\n".join(lines)

def main():
    vendors = ["netskope", "proofpoint", "qualys", "aruba", "imperva", "cyberark", "trendmicro", "guardicore"]
    
    print("=" * 70)
    print("🔍 DEBUG PROFUNDO DE VENDORS")
    print("=" * 70)
    print()
    
    os.makedirs(".github/out/vendors", exist_ok=True)
    
    reports = []
    for vendor in vendors:
        print(f"▶️  {vendor.upper():<15}", end=" ", flush=True)
        try:
            report = run_vendor_with_debug(vendor, ".github/out/vendors")
            reports.append(report)
            
            status_icon = "✅" if report["status"] == "OK" else "❌"
            print(f"{status_icon} ({report['elapsed_sec']:.1f}s, {report['json_size']} bytes)")
        except subprocess.TimeoutExpired:
            print(f"⏱️  TIMEOUT")
            reports.append({
                "vendor": vendor,
                "status": "TIMEOUT",
                "reason": "Timeout > 120s"
            })
        except Exception as e:
            print(f"💥 ERROR: {str(e)[:50]}")
            reports.append({
                "vendor": vendor,
                "status": "ERROR",
                "reason": str(e)
            })
    
    # Generar reportes
    print()
    print("=" * 70)
    print("📄 Generando reportes...")
    
    md_report = format_report_md(reports)
    
    md_path = ".github/out/vendor_debug_report.md"
    with open(md_path, "w") as f:
        f.write(md_report)
    print(f"✅ {md_path}")
    
    json_path = ".github/out/vendor_debug_report.json"
    with open(json_path, "w") as f:
        json.dump(reports, f, indent=2, ensure_ascii=False)
    print(f"✅ {json_path}")
    
    # Mostrar resumen en consola
    print()
    print(md_report)
    
    # Exit code
    failed = [r for r in reports if r["status"] != "OK"]
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
