#!/usr/bin/env python3
"""
Genera WorkflowDORA_EMAIL.zip: flujo Power Automate que envía email via Office 365
y notifica al canal Teams del SOC con confirmación.

Uso:
    Copia .github/input/.env.example a .github/input/.env y rellena los valores,
    luego ejecuta:  python .github/input/build_email_flow.py

Variables de entorno requeridas (o en .env):
    PA_FLOW_ID      Asset ID del flujo en Power Automate
    PA_ORIG_ZIP     Ruta al ZIP original exportado desde Power Automate
    TEAMS_GROUP_ID  Group ID del equipo Teams del SOC
    TEAMS_CHANNEL_ID  Channel ID del canal Teams del SOC
"""
import zipfile
import json
import os
import sys

# Cargar .env si existe (sin dependencias externas)
_env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_file):
    with open(_env_file, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        print(f"ERROR: variable de entorno requerida no definida: {name}")
        print(f"       Copia .github/input/.env.example a .github/input/.env y rellénala.")
        sys.exit(1)
    return val

FLOW_ID    = _require("PA_FLOW_ID")
GROUP_ID   = _require("TEAMS_GROUP_ID")
CHANNEL_ID = _require("TEAMS_CHANNEL_ID")

ORIG = os.environ.get("PA_ORIG_ZIP", os.path.join(os.path.dirname(__file__), "WorkflowDORA_original.zip"))
OUT  = os.path.join(os.path.dirname(__file__), "WorkflowDORA_EMAIL.zip")

if not os.path.exists(ORIG):
    print(f"ERROR: ZIP original no encontrado: {ORIG}")
    print(f"       Exporta el flujo desde Power Automate y colócalo como WorkflowDORA_original.zip")
    sys.exit(1)

# GUIDs estáticos para el nuevo conector Office 365 (se mapearán durante la importación)
O365_API_GUID  = "a2b3c4d5-e6f7-8901-abcd-ef1234567890"
O365_CONN_GUID = "b3c4d5e6-f7a8-9012-bcde-f12345678901"

# Detectar el prefijo del ZIP (nombre de la carpeta raíz dentro del ZIP)
_PREFIX = ""
with zipfile.ZipFile(ORIG) as _zf:
    for _n in _zf.namelist():
        if _n.endswith("/") and "/" not in _n.rstrip("/"):
            _PREFIX = _n
            break
PREFIX = _PREFIX

DEF_KEYS = [
    f"Microsoft.Flow/flows/{FLOW_ID}/definition.json",
    f"{PREFIX}Microsoft.Flow/flows/{FLOW_ID}/definition.json",
]
MANIFEST_KEYS = [
    "manifest.json",
    f"{PREFIX}manifest.json",
]
APIS_KEYS = [
    f"Microsoft.Flow/flows/{FLOW_ID}/apisMap.json",
    f"{PREFIX}Microsoft.Flow/flows/{FLOW_ID}/apisMap.json",
]
CONN_KEYS = [
    f"Microsoft.Flow/flows/{FLOW_ID}/connectionsMap.json",
    f"{PREFIX}Microsoft.Flow/flows/{FLOW_ID}/connectionsMap.json",
]


def modify_definition(d: dict) -> dict:
    props = d["properties"]
    definition = props["definition"]
    actions = definition["actions"]

    # Eliminar acciones de adjuntos/condición (ya no necesarias)
    for k in ["Initialize_variable_(Attachments)", "Attachments_is_null"]:
        actions.pop(k, None)

    # Acción: enviar email via Office 365 Outlook
    # Paso 1: publicar el informe en Teams (backup)
    actions["Publicar_informe_en_Teams"] = {
        "runAfter": {"Initialize_variable_(Body)": ["Succeeded"]},
        "type": "OpenApiConnection",
        "inputs": {
            "parameters": {
                "poster":                   "Flow bot",
                "location":                 "Channel",
                "body/recipient/groupId":   GROUP_ID,
                "body/recipient/channelId": CHANNEL_ID,
                "body/messageBody":         "@{variables('Body')?['teams_html']}",
            },
            "host": {
                "apiId":          "/providers/Microsoft.PowerApps/apis/shared_teams",
                "connectionName": "shared_teams",
                "operationId":    "PostMessageToConversation",
            },
            "authentication": "@parameters('$authentication')",
        },
    }

    # Paso 2: enviar email via Office 365 Outlook
    actions["Enviar_correo_electronico"] = {
        "runAfter": {"Publicar_informe_en_Teams": ["Succeeded"]},
        "type": "OpenApiConnection",
        "inputs": {
            "parameters": {
                "emailMessage/To":         "DESTINATARIO@EJEMPLO.COM",
                "emailMessage/Cc":         "CC@EJEMPLO.COM",
                "emailMessage/Bcc":        "BCC@EJEMPLO.COM",
                "emailMessage/Subject":    "@{variables('Body')?['subject']}",
                "emailMessage/Body":       "@{variables('Body')?['html']}",
                "emailMessage/Importance": "Normal",
            },
            "host": {
                "apiId":         "/providers/Microsoft.PowerApps/apis/shared_office365",
                "connectionName": "shared_office365",
                "operationId":   "SendEmailV2",
            },
            "authentication": "@parameters('$authentication')",
        },
    }

    # Paso 3: confirmación al SOC en Teams
    actions["Notificar_SOC_Teams"] = {
        "runAfter": {"Enviar_correo_electronico": ["Succeeded"]},
        "type": "OpenApiConnection",
        "inputs": {
            "parameters": {
                "poster":                       "Flow bot",
                "location":                     "Channel",
                "body/recipient/groupId":       GROUP_ID,
                "body/recipient/channelId":     CHANNEL_ID,
                "body/messageBody":             (
                    "<p>\u2705 <b>Informe DORA enviado</b></p>"
                    "<p>Para: @{variables('Body')?['to']}<br/>"
                    "Asunto: @{variables('Body')?['subject']}</p>"
                ),
            },
            "host": {
                "apiId":         "/providers/Microsoft.PowerApps/apis/shared_teams",
                "connectionName": "shared_teams",
                "operationId":   "PostMessageToConversation",
            },
            "authentication": "@parameters('$authentication')",
        },
    }

    # Añadir connectionReference para Office 365 Outlook
    props["connectionReferences"]["shared_office365"] = {
        "connectionName": "shared_office365",
        "source":         "Embedded",
        "id":             "/providers/Microsoft.PowerApps/apis/shared_office365",
        "tier":           "NotSpecified",
        "apiName":        "office365",
        "isProcessSimpleApiReferenceConversionAlreadyDone": False,
    }

    return d


def modify_manifest(m: dict) -> dict:
    resources = m["resources"]

    resources[O365_API_GUID] = {
        "id":   "/providers/Microsoft.PowerApps/apis/shared_office365",
        "name": "shared_office365",
        "type": "Microsoft.PowerApps/apis",
        "suggestedCreationType": "Existing",
        "details": {
            "displayName": "Office 365 Outlook",
            "iconUri": "https://static.powerapps.com/resource/ppcr/releases/v1.0.1812/1.0.1812.4744/office365/icon.png",
        },
        "configurableBy": "System",
        "hierarchy":      "Child",
        "dependsOn":      [],
    }
    resources[O365_CONN_GUID] = {
        "type": "Microsoft.PowerApps/apis/connections",
        "suggestedCreationType": "Existing",
        "creationType":          "Existing",
        "details": {
            "displayName": "darell@aiuken.com",
            "iconUri": "https://static.powerapps.com/resource/ppcr/releases/v1.0.1812/1.0.1812.4744/office365/icon.png",
        },
        "configurableBy": "User",
        "hierarchy":      "Child",
        "dependsOn":      [O365_API_GUID],
    }

    # Añadir dependencias al flujo principal
    resources[FLOW_ID]["dependsOn"].append(O365_API_GUID)
    resources[FLOW_ID]["dependsOn"].append(O365_CONN_GUID)

    return m


# ── Leer ZIP original en memoria ─────────────────────────────────────────────
entries: dict[str, bytes] = {}
with zipfile.ZipFile(ORIG, "r") as zf:
    for name in zf.namelist():
        with zf.open(name) as f:
            entries[name] = f.read()

# ── Aplicar modificaciones ────────────────────────────────────────────────────
for key in DEF_KEYS:
    if key in entries:
        d = json.loads(entries[key].decode("utf-8"))
        d = modify_definition(d)
        entries[key] = json.dumps(d, ensure_ascii=False).encode("utf-8")
        print(f"OK definition: {key}")

for key in MANIFEST_KEYS:
    if key in entries:
        m = json.loads(entries[key].decode("utf-8"))
        m = modify_manifest(m)
        entries[key] = json.dumps(m, ensure_ascii=False).encode("utf-8")
        print(f"OK manifest:   {key}")

for key in APIS_KEYS:
    if key in entries:
        a = json.loads(entries[key].decode("utf-8"))
        a["shared_office365"] = O365_API_GUID
        entries[key] = json.dumps(a, ensure_ascii=False).encode("utf-8")
        print(f"OK apisMap:    {key}")

for key in CONN_KEYS:
    if key in entries:
        c = json.loads(entries[key].decode("utf-8"))
        c["shared_office365"] = O365_CONN_GUID
        entries[key] = json.dumps(c, ensure_ascii=False).encode("utf-8")
        print(f"OK connMap:    {key}")

# ── Escribir nuevo ZIP ────────────────────────────────────────────────────────
if os.path.exists(OUT):
    os.remove(OUT)

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for name, data in entries.items():
        zf.writestr(name, data)

print(f"\nDONE: {OUT}")
