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

    # Firma corporativa HTML (estática, se concatena al body del email)
    FIRMA_HTML = (
        '<table border="0" cellpadding="0" cellspacing="0" style="font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#333333;margin-top:20px;border-top:1px solid #cccccc;max-width:600px;">'
        '<tr><td style="padding-top:12px;">'
        '<p style="margin:0 0 8px 0;color:#666666;">--<br>-</p>'
        '<p style="margin:0 0 10px 0;"><img src="https://www.aiuken.com/user/themes/motor/images/logo10.jpg" alt="Aiuken Cybersecurity" width="160" style="display:block;"></p>'
        '<p style="margin:0 0 2px 0;font-size:13px;font-weight:bold;color:#1a1a1a;">Darell P\u00e9rez Bango</p>'
        '<p style="margin:0 0 8px 0;font-size:12px;color:#555555;">SOC Area Manager</p>'
        '<table border="0" cellpadding="0" cellspacing="0" style="font-size:12px;">'
        '<tr><td style="padding:1px 8px 1px 0;font-weight:bold;color:#444444;white-space:nowrap;">Email:</td>'
        '<td><a href="mailto:darell@aiuken.com" style="color:#1a73e8;text-decoration:none;">darell@aiuken.com</a></td></tr>'
        '<tr><td></td><td><a href="https://www.aiuken.com" style="color:#1a73e8;text-decoration:none;">www.aiuken.com</a></td></tr>'
        '<tr><td style="padding:1px 8px 1px 0;font-weight:bold;color:#444444;white-space:nowrap;">Tel:</td><td>+34 911 41 32 19</td></tr>'
        '<tr><td></td><td>+56 229 38 22 04</td></tr>'
        '<tr><td style="padding:1px 8px 1px 0;font-weight:bold;color:#444444;white-space:nowrap;">Mov:</td><td>+34 648 04 45 02</td></tr>'
        '<tr><td style="padding:1px 8px 1px 0;font-weight:bold;color:#444444;white-space:nowrap;">PGP Key ID:</td>'
        '<td><a href="https://keys.openpgp.org/search?q=0x6DAC1D42" style="color:#1a73e8;text-decoration:none;">0x6DAC1D42</a></td></tr>'
        '</table>'
        '<p style="margin:12px 0 6px 0;"><img src="https://www.aiuken.com/wp-content/uploads/2025/04/Pie-Firma-Aiuken.png" alt="Aiuken Certifications" width="480" style="display:block;"></p>'
        '<p style="margin:12px 0 2px 0;font-size:10px;color:#777777;max-width:580px;line-height:1.4;">'
        '<strong>LEGAL NOTICE:</strong> This message and its attachments are confidential and may only be used by the person or entity to which they are addressed. '
        'This message may contain confidential or legally protected information. There is no waiver of confidentiality or professional secrecy for any defective or erroneous transmission. '
        'If you have received this message by mistake, notify the sender. In accordance with Regulation (EU) 2016/679 of the European Parliament and of the Council, of April 27, 2016, '
        'on the protection of natural persons regarding the processing of personal data and the free circulation of such data, Aiuken Solutions S.L.U., informs you of the following points: '
        'The data provided by you will become part of the activity log of the company of Aiuken Solutions S.L.U. The data provided by you will be used for management purposes of the relationship '
        'by which they were collected, respecting the principles of legality, loyalty and transparency; limitation of purpose; minimization of treated personal data; accuracy of the personal data processed; '
        'limitation of the term of conservation, as well as integrity and confidentiality, through the adoption of the applicable security measures. '
        'Aiuken Solutions SL has adopted the security measures required based on the level of data involved, installing the necessary technical and organizational measures, considering the state of the technology, '
        'in order to avoid their loss, alteration, inappropriate use or unauthorized access to them. '
        'To exercise your rights of access, rectification, portability, opposition or deletion should be directed to the address of the controller: '
        'Aiuken Solutions S.L.U., Calle Francisco Tom\u00e1s y Valiente, 2, 28660 Boadilla del Monte, Madrid or to the e-mail address: lopd@aiuken.com. '
        'If you want to know more about our privacy policy, click here: www.aiuken.com</p>'
        '<p style="margin:4px 0 0 0;font-size:10px;color:#777777;font-style:italic;">Do not print this mail if it is not necessary. Saving paper protects the environment</p>'
        '</td></tr></table>'
    )

    # Initialize variable: Firma (se inicializa justo después de Body)
    actions["Initialize_variable_(Firma)"] = {
        "runAfter": {"Initialize_variable_(Body)": ["Succeeded"]},
        "type": "InitializeVariable",
        "inputs": {
            "variables": [{
                "name":  "Firma",
                "type":  "string",
                "value": FIRMA_HTML,
            }]
        },
    }

    # Paso 1: publicar el informe en Teams (backup)
    actions["Publicar_informe_en_Teams"] = {
        "runAfter": {"Initialize_variable_(Firma)": ["Succeeded"]},
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
                "emailMessage/Body":       "@{concat(variables('Body')?['html'], variables('Firma'))}",
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
