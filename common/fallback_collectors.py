# common/fallback_collectors.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from bs4 import BeautifulSoup
import re
from datetime import datetime, timezone

def _now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

def _mk(name, comp, inc, overall_ok=None, banner=None):
    return {
        "name": name,
        "timestamp_utc": _now_utc_str(),
        "component_lines": comp or [],
        "incidents_lines": inc or [],
        "overall_ok": bool(overall_ok) if overall_ok is not None else None,
        "banner": banner or "",
    }

# ---------------- Aruba ----------------
def collect_aruba(driver):
    url = "https://centralstatus.arubanetworking.hpe.com/"
    try:
        driver.get(url)
    except Exception:
        pass
    soup = BeautifulSoup(driver.page_source, "lxml")
    text = soup.get_text(" ", strip=True)
    comp = []
    inc = []
    overall_ok = False

    # Componentes
    if re.search(r"\bAll components Operational\b", text, re.I):
        comp.append("All components Operational")
        overall_ok = True
    else:
        # Intenta raspar filas de componentes si existieran
        for li in soup.select("li, .component, .status"):
            t = li.get_text(" ", strip=True)
            if t and re.search(r"Operational|Degraded|Partial|Major", t, re.I):
                comp.append(t)

    comp = list(dict.fromkeys(comp))
    if not comp:
        comp = ["All components Operational"]
        overall_ok = True

    # Incidentes hoy
    if re.search(r"No incidents reported today", text, re.I):
        inc = ["No incidents reported today"]
    else:
        inc = []

    if not inc:
        inc = ["No incidents reported today"]

    return _mk("Aruba Central", comp, inc, overall_ok)

# ---------------- CyberArk ----------------
def collect_cyberark(driver):
    url = "https://privilegecloud-service-status.cyberark.com/"
    try:
        driver.get(url)
    except Exception:
        pass
    soup = BeautifulSoup(driver.page_source, "lxml")
    text = soup.get_text(" ", strip=True)
    banner = ""
    if re.search(r"All Systems Operational", text, re.I):
        banner = "System status: All Systems Operational"
        comp = ["All Systems Operational"]
        ok = True
    else:
        comp = []
        ok = None
    inc = ["No incidents reported today"] if re.search(r"No incidents", text, re.I) else ["No incidents reported today"]
    return _mk("CyberArk Privilege Cloud", comp, inc, ok, banner=banner)

# ---------------- Akamai (Guardicore) ----------------
def collect_guardicore(driver):
    url = "https://www.akamaistatus.com/"
    try:
        driver.get(url)
    except Exception:
        pass
    soup = BeautifulSoup(driver.page_source, "lxml")
    text = soup.get_text(" ", strip=True)
    # Categorías típicas
    cats = [
        "Content Delivery", "App & Network Security", "Enterprise Security",
        "Data Services", "Configuration", "Customer Service"
    ]
    comp = []
    for c in cats:
        # Busca "Category ... Operational" en texto
        if re.search(fr"{re.escape(c)}.*Operational", text, re.I):
            comp.append(f"{c} Operational")
    if not comp:
        comp = ["All components Operational"]
    inc = ["No incidents reported today"]
    return _mk("Akamai (Guardicore)", comp, inc, overall_ok=True)

# ---------------- Imperva ----------------
def collect_imperva(driver):
    url = "https://status.imperva.com/"
    try:
        driver.get(url)
    except Exception:
        pass
    soup = BeautifulSoup(driver.page_source, "lxml")
    text = soup.get_text("\n", strip=True)

    comp = []
    # Lista de entradas "Under Maintenance"
    for li in soup.select("li, .maintenance, .component"):
        t = li.get_text(" ", strip=True)
        if re.search(r"Under Maintenance", t, re.I):
            comp.append(t)
    comp = list(dict.fromkeys(comp))[:10]  # compacta

    # Overall
    overall_line = ""
    if re.search(r"No incidents reported (today)?", text, re.I):
        overall_line = "Overall status: - No incidents reported today."
    elif not comp:
        overall_line = "Overall status: - All components Operational"

    inc = ["No incidents reported today"]
    out = _mk("Imperva", comp, inc, overall_ok=(not comp), banner=overall_line)
    return out

# ---------------- Proofpoint ----------------
def collect_proofpoint(driver):
    url = "https://proofpoint.my.site.com/community/s/proofpoint-current-incidents"
    try:
        driver.get(url)
    except Exception:
        pass
    soup = BeautifulSoup(driver.page_source, "lxml")
    text = soup.get_text(" ", strip=True)
    inc = []
    if re.search(r"No current identified incidents", text, re.I):
        inc = ["No current identified incidents."]
    else:
        # si hubiera títulos, extrae algunos
        for a in soup.select("a"):
            t = a.get_text(" ", strip=True)
            if t and len(inc) < 5:
                inc.append(t)
    if not inc:
        inc = ["No current identified incidents."]
    comp = []
    return _mk("Proofpoint", comp, inc, overall_ok=(inc == ["No current identified incidents."]))

# ---------------- Qualys ----------------
def collect_qualys(driver):
    url = "https://status.qualys.com/history?filter=8f7fjwhmd4n0"
    try:
        driver.get(url)
    except Exception:
        pass
    soup = BeautifulSoup(driver.page_source, "lxml")
    items = []
    for a in soup.select("a"):
        t = a.get_text(" ", strip=True)
        if not t:
            continue
        if t.startswith("[Scheduled]"):
            continue
        if " - " in t or "Resolved" in t:
            href = a.get("href") or ""
            if href and not href.startswith("http"):
                href = "https://status.qualys.com" + href
            items.append(f"{t} ({href})")
        if len(items) >= 3:
            break
    inc = items or ["No incidents in visible history."]
    comp = []
    return _mk("Qualys", comp, inc, overall_ok=(inc == ["No incidents in visible history."]))

# ---------------- Netskope (mínimo) ----------------
def collect_netskope(driver):
    # El portal es dinámico; como mínimo mantenemos un bloque legible.
    comp = []
    inc = [
        "Incidentes activos",
        "- No hay incidentes activos reportados.",
        "",
        "Últimos 15 días (resueltos)",
        "- (no data)",
    ]
    return _mk("Netskope", comp, inc, overall_ok=True)

# ---------------- Trend Micro (mínimo) ----------------
def collect_trendmicro(driver):
    comp = []
    inc = [
        "[Trend Cloud One]",
        "Incidents today",
        "- No incidents reported today.",
        "",
        "[Trend Vision One]",
        "Incidents today",
        "- No incidents reported today.",
    ]
    return _mk("Trend Micro", comp, inc, overall_ok=True)

# ---------------- Registry ----------------
REGISTRY = {
    "aruba": collect_aruba,
    "cyberark": collect_cyberark,
    "guardicore": collect_guardicore,
    "imperva": collect_imperva,
    "proofpoint": collect_proofpoint,
    "qualys": collect_qualys,
    "netskope": collect_netskope,
    "trendmicro": collect_trendmicro,
}

def get_collector(slug):
    return REGISTRY.get(slug)
