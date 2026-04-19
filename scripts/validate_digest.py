#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Valida que digest_data.json tenga datos reales antes de enviar.
Evita el envío de reportes vacíos cuando los vendors fallan.

Uso:
    python scripts/validate_digest.py --data .github/out/digest_data.json
    
Exit codes:
    0 = Válido, proceder a enviar
    1 = Inválido, STOP - no enviar nada
"""

import json
import sys
import argparse
from datetime import datetime

def validate_digest(path: str) -> tuple[bool, str]:
    """Valida que el digest tenga datos reales. Retorna (válido, mensaje)."""
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, "❌ digest_data.json no existe"
    except json.JSONDecodeError:
        return False, "❌ digest_data.json no es JSON válido"
    
    if not isinstance(data, dict):
        return False, "❌ digest_data.json no es un diccionario"
    
    # Validaciones críticas
    checks = [
        ("NUM_PROVEEDORES", "Número de proveedores"),
        ("DETALLES_POR_VENDOR_TEXTO", "Detalles por fabricante"),
        ("OBS_CLAVE", "Observación clave"),
        ("IMPACTO_CLIENTE_SI_NO", "Impacto en cliente"),
        ("ACCION_SUGERIDA", "Acción sugerida"),
    ]
    
    missing = []
    empty = []
    
    for key, desc in checks:
        if key not in data:
            missing.append(f"{desc} ({key})")
        elif not data[key]:  # None, "", [], 0 empty
            empty.append(f"{desc} ({key})")
    
    if missing:
        return False, f"❌ Campos faltantes: {', '.join(missing)}"
    
    # El problema más común: sin detalles de vendors
    if not data.get("DETALLES_POR_VENDOR_TEXTO", "").strip():
        return False, (
            "❌ CRÍTICO: Sin datos de fabricantes\n"
            "   Posibles causas:\n"
            "   - Los vendors fallaron en el scraping\n"
            "   - No hay JSONs de vendors en .github/out/vendors/\n"
            "   - Los sitios de status estaban caídos\n"
            "   \n"
            "   ⚠️ NO se enviará este digest para evitar reportes en blanco"
        )
    
    # Validar que haya al menos 1 proveedor
    num_prov = data.get("NUM_PROVEEDORES", 0)
    if num_prov == 0:
        return False, (
            "❌ Sin proveedores (NUM_PROVEEDORES=0)\n"
            "   Los scraping de vendors no completó correctamente"
        )
    
    # Warnings (pero no fallan)
    warnings = []
    if num_prov < 8:
        warnings.append(f"⚠️  ADVERTENCIA: Solo {num_prov} de 8 proveedores (faltaron {8 - num_prov})")
    
    # OK
    msg = f"✅ Digest válido ({num_prov} proveedores)"
    if warnings:
        msg = msg + "\n" + "\n".join(warnings)
    
    return True, msg

def main():
    ap = argparse.ArgumentParser(description="Valida que digest_data.json tenga datos reales")
    ap.add_argument("--data", required=True, help="Ruta a digest_data.json")
    args = ap.parse_args()
    
    print("🔍 Validando digest_data.json...\n")
    valid, msg = validate_digest(args.data)
    
    print(msg)
    print()
    
    if not valid:
        print("=" * 70)
        print("🛑 VALIDACIÓN FALLIDA - NO SE ENVIARÁ ESTE DIGEST")
        print("=" * 70)
        sys.exit(1)
    
    print("=" * 70)
    print("✅ Proceder con envío de digest")
    print("=" * 70)
    sys.exit(0)

if __name__ == "__main__":
    main()
