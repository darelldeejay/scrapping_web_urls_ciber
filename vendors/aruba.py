# vendors/aruba.py
import os
import re
import time
import traceback
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common.browser import start_driver
from common.notify import send_telegram, send_teams
from common.format import header

URL = "https://centralstatus.arubanetworking.hpe.com/"
SAVE_HTML = os.getenv("SAVE_HTML", "0") == "1"

# Estados típicos en el banner de zonas
STATUS_WORDS = [
    "Operational",
    "Degraded Performance",
    "Partial Outage",
    "Major Outage",
    "Under Maintenance",
]

ISSUE_STATUS_RE = re.compile(r"(Degraded Performance|Partial Outage|Major Outage|Under Maintenance)", re.I)
OPERATIONAL_RE = re.compile(r"\bOperational\b", re.I)
NO_INCIDENTS_TODAY_RE = re.compile(r"No incidents reported today", re.I)

# Fecha del día en formato del sitio (ej: "Aug 17, 2025")
def today_header_strings():
    now = datetime.utcnow()
    # con cero y sin cero en el día (por si el sitio no pone el 0 a la izquierda)
    with_zero = now.strftime("%b %d, %Y")   # "Aug 07, 2025"
    no_zero  = now.strftime("%b %-d, %Y") if "%" in "%-d" else with_zero.replace(" 0", " ")
    # fallback por si el entorno no soporta %-d
    no_zero = with_zero.replace(" 0", " ")
    return {with_zero, no_zero}

def wait_for_page(driver):
    # Espera a que aparezca algo del banner de zonas o el texto de “No incidents reported today”
    WebDriverWait(driver, 25).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
    )
    for _ in range(40):
        body = driver.find_element(By.TAG_NAME, "body").text
        if (ISSUE_STATUS_RE.search(body) or
            OPERATIONAL_RE.search(body) or
            NO_INCIDENTS_TODAY_RE.search(body) or
            any(s in body for s in today_header_strings())):
            return
        time.sleep(0.5)

def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def parse_regions_with_issues(soup: BeautifulSoup):
    """
    Devuelve una lista de dicts {region, status} SOLO para regiones que no están 'Operational'.
    Heurística: buscamos nodos con los estados problemáticos y extraemos el texto del contenedor cercano.
    """
    items = []
    # Candidatos: cualquier elemento cuyo texto contenga un estado problemático
    candidates = []
    for tag in soup.find_all(True):
        txt = collapse_ws(getattr(tag, "get_text", lambda *a, **k: "")(" ", strip=True))
        if not txt:
            continue
        m = ISSUE_STATUS_RE.search(txt)
        if m:
            candidates.append((tag, txt, m.group(1)))

    seen = set()
    for tag, txt, status in candidates:
        # Sube por ancestros para captar el bloque (tile) con el nombre de la región
        node = tag
        region = None
        for _ in range(5):
            if not node:
                break
            block_txt = collapse_ws(getattr(node, "get_text", lambda *a, **k: "")(" ", strip=True))
            if not block_txt:
                node = getattr(node, "parent", None)
                continue
            # El nombre de la región suele ir antes del estado dentro del mismo bloque
            # Tomamos el prefijo anterior a la primera aparición del estado
            pos = block_txt.lower().find(status.lower())
            if pos > 0:
                prefix = collapse_ws(block_txt[:pos])
                # limpia prefijo de palabras de estado u otras repeticiones
                for sw in STATUS_WORDS:
                    prefix = re.sub(re.escape(sw), "", prefix, flags=re.I)
                prefix = collapse_ws(prefix)
                # Si el prefijo es muy largo, intenta quedarte con la última línea/parte
                if len(prefix) > 60 and " " in prefix:
                    prefix = prefix.split(" ")[-5:]
                    prefix = " ".join(prefix)
                if prefix:
                    region = prefix
                    break
            node = getattr(node, "parent", None)

        region = region or "Region"
        key = (region.lower(), status.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append({"region": region, "status": status})

    return items

def parse_incidents_today(soup: BeautifulSoup):
    """
    Devuelve:
      - {"no_incidents": True} si aparece “No incidents reported today.”
      - {"no_incidents": False, "items": [...] } si encontramos texto bajo la fecha de hoy
        (intentamos listar líneas/elementos simples; si no, devolvemos un placeholder).
    """
    full_text = collapse_ws(soup.get_text(" ", strip=True))
    if NO_INCIDENTS_TODAY_RE.search(full_text):
        return {"no_incidents": True}

    # Busca un encabezado con la fecha de hoy
    today_opts = today_header_strings()
    date_node = None
    for s in today_opts:
        # Busca el texto en nodos para acotar el bloque del día
        date_node = soup.find(string=re.compile(re.escape(s), re.I))
        if date_node:
            break

    if not date_node:
        # No encontramos el encabezado ni el “no incidents”; reportamos desconocido
        return {"no_incidents": False, "items": ["(No se pudo desglosar los incidentes del día en la página)"]}

    # Intenta recoger items cercanos al encabezado (hermanos o dentro del mismo contenedor)
    items = []
    parent = getattr(date_node, "parent", None)
    container = parent
    # Sube algo por el DOM para intentar capturar el bloque del día
    for _ in range(3):
        if not container:
            break
        # busca listas/paragraphs dentro
        for li in container.find_all(["li"]):
            t = collapse_ws(li.get_text(" ", strip=True))
            if t and not NO_INCIDENTS_TODAY_RE.search(t):
                items.append(t)
        for p in container.find_all(["p"]):
            t = collapse_ws(p.get_text(" ", strip=True))
            if t and not NO_INCIDENTS_TODAY_RE.search(t):
                items.append(t)
        if items:
            break
        container = getattr(container, "parent", None)

    # Dedup y limpia
    clean = []
    seen = set()
    for t in items:
        if t.lower() in seen:
            continue
        seen.add(t.lower())
        clean.append(t)

    if not clean:
        # Si no encontramos elementos, devolvemos un placeholder
        return {"no_incidents": False, "items": ["(Incidentes reportados hoy — ver detalle en la web)"]}

    # Evita capturar la propia fecha como item
    clean = [t for t in clean if t not in today_opts]

    return {"no_incidents": len(clean) == 0, "items": clean}

def format_message(regions_with_issues, today_info):
    lines = [header("Aruba Central")]

    # Zonas con problemas
    if regions_with_issues:
        lines.append("\n<b>Zonas con estado no operativo</b>")
        for r in regions_with_issues:
            lines.append(f"- {r['region']}: <b>{r['status']}</b>")
    else:
        lines.append("\n<b>Zonas</b>\n- Todas las zonas están Operational.")

    # Incidentes del día
    # Fecha en cabecera como aparece en el sitio
    today_str = list(today_header_strings())[0]
    lines.append(f"\n<b>Incidentes de hoy ({today_str})</b>")
    if today_info.get("no_incidents"):
        lines.append("- No incidents reported today.")
    else:
        items = today_info.get("items") or []
        if not items:
            lines.append("- (Incidentes reportados hoy — ver detalle en la web)")
        else:
            for i, t in enumerate(items, 1):
                lines.append(f"{i}. {t}")

    return "\n".join(lines)

def run():
    driver = start_driver()
    try:
        driver.get(URL)
        wait_for_page(driver)

        html = driver.page_source
        if SAVE_HTML:
            try:
                with open("aruba_page_source.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print("💾 HTML guardado en aruba_page_source.html")
            except Exception as e:
                print(f"No se pudo guardar HTML: {e}")

        soup = BeautifulSoup(html, "lxml")
        regions = parse_regions_with_issues(soup)
        today = parse_incidents_today(soup)

        msg = format_message(regions, today)
        print("\n===== ARUBA =====")
        print(msg)
        print("=================\n")

        send_telegram(msg)
        send_teams(msg)

    except Exception as e:
        print(f"[aruba] ERROR: {e}")
        traceback.print_exc()
        send_telegram(f"<b>Aruba Central - Monitor</b>\nSe produjo un error:\n<pre>{str(e)}</pre>")
        send_teams(f"❌ Aruba Central - Monitor\nSe produjo un error: {str(e)}")
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass
