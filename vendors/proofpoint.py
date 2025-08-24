# vendors/proofpoint.py
# -*- coding: utf-8 -*-
"""
Proofpoint — soporte dual:
- run(): ejecución clásica con Selenium + notificación (Telegram/Teams)
- collect(driver): reutiliza el parseo para export JSON (sin notificar)
  con formato normalizado para el digest.

Reglas aplicadas:
- Página: https://proofpoint.my.site.com/community/s/proofpoint-current-incidents
- Caso habitual: banner "No current identified incidents".
- Si en algún momento listan incidentes, se aceptan entradas que contengan "Incident ####"
  y se intenta adjuntar su URL (si existe).
"""

import os
import re
import time
import traceback
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams

URL = "https://proofpoint.my.site.com/community/s/proofpoint-current-incidents"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

NO_INCIDENTS_RE = re.compile(r"\bNo current identified incidents\b", re.I)
INCIDENT_ID_RE = re.compile(r"\bIncident\s+\d+\b", re.I)

# ---------------- Utilidades ---------------- #

def now_utc_str() -> str:
    """Para mensajes legacy: con sufijo explícito UTC."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def _now_utc_clean() -> str:
    """Para export JSON: sin 'UTC' (se añade al render del digest)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def wait_for_page(driver) -> None:
    """
    Espera a que cargue el encabezado o el mensaje de "No incidents".
    Usa varios predicados por si el DOM cambia ligeramente.
    """
    preds = [
        (By.XPATH, "//*[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'PROOFPOINT CURRENT INCIDENTS')]"),
        (By.XPATH, "//*[contains(translate(., 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), 'NO CURRENT IDENTIFIED INCIDENTS')]"),
        (By.CSS_SELECTOR, "main, body")  # fallback genérico
    ]
    last_err = None
    for by, sel in preds:
        try:
            WebDriverWait(driver, 20).until(EC.presence_of_element_located((by, sel)))
            return
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err

# ---------------- Parseo ---------------- #

def page_text(soup: BeautifulSoup) -> str:
    try:
        return " ".join([s.strip() for s in soup.stripped_strings])
    except Exception:
        return collapse_ws(soup.get_text(" ", strip=True))

def parse_incidents_from_html(html: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """
    Devuelve (activos, pasados, banner_text)
    - activos: lista de dicts mínimos con title/url (Proofpoint no suele exponer tiempos aquí)
    - pasados: siempre vacío (esta URL solo publica incidentes actuales)
    - banner_text: "No current identified incidents" cuando aplica
    """
    soup = BeautifulSoup(html, "lxml")
    full_txt = page_text(soup)

    # Caso habitual: no hay incidentes
    if NO_INCIDENTS_RE.search(full_txt):
        return [], [], "No current identified incidents"

    # Buscar entradas con "Incident ####"
    incidents = []
    # Usamos strings que matcheen el patrón
    for node in soup.find_all(string=INCIDENT_ID_RE):
        title = collapse_ws(str(node))
        container = getattr(node, "parent", None)
        url = None

        # Intenta localizar un <a> con href real (evitar enlaces de navegación de Salesforce)
        anchor = None
        cur = container
        steps = 0
        while cur and steps < 6 and anchor is None:
            if hasattr(cur, "find"):
                a = cur.find("a", href=True)
                if a and a.get("href"):
                    anchor = a
                    break
            cur = getattr(cur, "parent", None)
            steps += 1

        if anchor:
            href = anchor.get("href", "")
            if href.startswith("http"):
                url = href
            elif href.startswith("/"):
                url = "https://proofpoint.my.site.com" + href
            # Si el <a> tiene texto "mejor" para título, úsalo
            a_txt = collapse_ws(anchor.get_text(" ", strip=True))
            if a_txt and INCIDENT_ID_RE.search(a_txt):
                title = a_txt

        incidents.append({
            "title": title or "Incident",
            "status": "Update",
            "url": url,
            "started_at": None,
            "ended_at": None,
        })

    # Deduplicar por (title,url)
    uniq = []
    seen = set()
    for it in incidents:
        key = (it["title"], it.get("url") or "")
        if key in seen:
            continue
        seen.add(key); uniq.append(it)

    if not uniq:
        # Si no identificamos ninguno de forma fiable, tratamos como "no incidents"
        return [], [], "No current identified incidents"

    return uniq, [], None

# ---------------- Formato de salida (texto limpio) ---------------- #

def format_incident_line(it: Dict[str, Any], idx: int) -> List[str]:
    title = collapse_ws(it.get("title") or "Incident")
    url = it.get("url") or ""
    main = f"{idx}. {title}"
    if url:
        main += f" ({url})"
    # Proofpoint no aporta fechas aquí
    return [main]

def format_message(activos: List[Dict[str, Any]], banner_text: Optional[str]) -> str:
    """
    Mensaje para Telegram/Teams (texto plano, sin HTML).
    """
    lines: List[str] = [
        "Proofpoint - Estado de Incidentes",
        now_utc_str(),
        ""
    ]
    # Si hay banner explícito de "No current identified incidents", muéstralo como línea simple
    if banner_text and not activos:
        lines.append("Incidentes activos")
        lines.append("- No hay incidentes activos reportados.")
    else:
        lines.append("Incidentes activos")
        if not activos:
            lines.append("- No hay incidentes activos reportados.")
        else:
            for i, it in enumerate(activos, 1):
                lines.extend(format_incident_line(it, i))

    return "\n".join(lines)

# ---------------- Export normalizado para digest ---------------- #

def collect(driver) -> Dict[str, Any]:
    """
    Reutiliza Selenium+BS para devolver dict normalizado:
      {
        "name": "Proofpoint",
        "timestamp_utc": "YYYY-MM-DD HH:MM",
        "component_lines": [],
        "incidents_lines": ["Incidentes activos", "- No hay incidentes ..."] o líneas con items,
        "overall_ok": True/False,
        "banner": "System status: ..." (opcional; aquí usamos No current identified incidents)
      }
    """
    driver.get(URL)
    wait_for_page(driver)
    time.sleep(0.5)

    html = driver.page_source
    if SAVE_HTML:
        try:
            with open("proofpoint_page_source.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

    activos, pasados, banner_text = parse_incidents_from_html(html)

    # component_lines: Proofpoint no expone componentes -> vacío
    component_lines: List[str] = []

    # incidents_lines
    incidents_lines: List[str] = ["Incidentes activos"]
    if not activos:
        incidents_lines.append("- No hay incidentes activos reportados.")
    else:
        for i, it in enumerate(activos, 1):
            incidents_lines.extend(format_incident_line(it, i))

    overall_ok = (len(activos) == 0)

    out: Dict[str, Any] = {
        "name": "Proofpoint",
        "timestamp_utc": _now_utc_clean(),
        "component_lines": component_lines,
        "incidents_lines": incidents_lines,
        "overall_ok": overall_ok,
    }
    if banner_text:
        # Lo exponemos como banner genérico; el renderer lo mostrará como línea suelta si no hay componentes
        out["banner"] = banner_text
    return out

# ---------------- Runner (notificación clásica) ---------------- #

def run():
    driver = start_driver()
    try:
        driver.get(URL)
        wait_for_page(driver)
        time.sleep(0.5)

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("proofpoint_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML guardado en proofpoint_page_source.html")
            except Exception as e:
                print(f"No se pudo guardar HTML: {e}")

        activos, pasados, banner_text = parse_incidents_from_html(html)

        resumen = format_message(activos, banner_text)
        print("\n===== PROOFPOINT =====")
        print(resumen)
        print("======================\n")

        send_telegram(resumen)
        send_teams(resumen)

    except Exception as e:
        print(f"[proofpoint] ERROR: {e}")
        traceback.print_exc()
        # Mensajes simples, sin HTML
        send_telegram(f"Proofpoint - Monitor\nError:\n{str(e)}")
        send_teams(f"❌ Proofpoint - Monitor\nError: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
