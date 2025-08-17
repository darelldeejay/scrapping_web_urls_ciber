# vendors/aruba.py
# Aruba Central (Statuspage) scraper
# - Solo notifica componentes NO operacionales.
# - Mantiene textos en inglés (no traduce "Operational", "No incidents reported today.", etc.).
# - Resume los incidentes del día (primer bloque de la lista de "Past Incidents").

from bs4 import BeautifulSoup
from datetime import datetime
import time

URL = "https://centralstatus.arubanetworking.hpe.com/"

def _utc_now_stamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def run(driver) -> str:
    driver.get(URL)
    time.sleep(5)
    soup = BeautifulSoup(driver.page_source, "html.parser")

    header = f"Aruba - Estado de Incidentes\n{_utc_now_stamp()}\n"

    # --- Componentes: listar solo los NO operacionales ---
    non_operational = []
    for comp in soup.select(".components-section .component-inner-container"):
        status_attr = (comp.get("data-component-status") or "").strip().lower()
        name_el = comp.select_one(".name")
        status_text_el = comp.select_one(".component-status")
        name = name_el.get_text(strip=True) if name_el else "Unknown"
        status_text = status_text_el.get_text(strip=True) if status_text_el else status_attr or "Unknown"
        if status_attr != "operational":
            # Ej.: "- EU-1: Application Degradation"
            non_operational.append(f"- {name}: {status_text}")

    comp_section = ["\nComponent status"]
    if non_operational:
        comp_section.extend(non_operational)
    else:
        comp_section.append("- All components Operational")

    # --- Incidentes del día (primer bloque de la lista) ---
    incidents_section = ["\nIncidents today"]
    day_block = soup.select_one(".incidents-list .status-day")

    if day_block:
        # Si el día dice "No incidents reported today."
        classes = day_block.get("class", [])
        if "no-incidents" in classes:
            p = day_block.select_one("p.color-secondary")
            msg = p.get_text(strip=True) if p else "No incidents reported today."
            incidents_section.append(f"- {msg}")
        else:
            # Hay incidentes en ese día (primer bloque)
            for inc in day_block.select(".incident-container"):
                title_el = inc.select_one(".incident-title a")
                title = title_el.get_text(strip=True) if title_el else "Incident"

                # Usamos la última actualización mostrada (suele estar arriba: Resolved/Investigating)
                updates = inc.select(".updates-container .update")
                latest = updates[0] if updates else None
                if latest:
                    status_word = (latest.select_one("strong").get_text(strip=True)
                                   if latest.select_one("strong") else "").strip()
                    time_text = (latest.select_one("small").get_text(strip=True)
                                 if latest.select_one("small") else "").strip()
                    # Ej.: "• Resolved — [EU3/APAC] : SD-WAN ... (Aug 13, 02:40 PDT)"
                    incidents_section.append(f"• {status_word} — {title} ({time_text})")
                else:
                    incidents_section.append(f"• {title}")
    else:
        incidents_section.append("- Unable to read incidents section")

    return header + "\n".join(comp_section + incidents_section)
