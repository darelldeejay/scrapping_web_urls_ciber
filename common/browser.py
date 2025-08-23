# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException

def make_driver(headless: bool = True, page_load_timeout: int = 60) -> webdriver.Chrome:
    """
    Crea un Chrome para CI (GitHub Actions) usando Selenium Manager.
    No requiere instalar Chrome/Chromedriver manualmente.
    """
    opts = Options()
    if headless:
        # Headless moderno (más estable en CI)
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--window-size=1365,1024")

    # User-Agent configurable (algunos sites son sensibles)
    ua = os.getenv("SCRAPER_UA") or (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )
    opts.add_argument(f"--user-agent={ua}")

    driver = webdriver.Chrome(options=opts)  # Selenium Manager resuelve binarios compatibles
    try:
        driver.set_page_load_timeout(page_load_timeout)
        driver.set_script_timeout(30)
        driver.implicitly_wait(0)
    except Exception:
        pass
    return driver

# Compatibilidad retro para vendors que aún importan start_driver
def start_driver(headless: bool = True, page_load_timeout: int = 60) -> webdriver.Chrome:
    """
    Alias legacy para compatibilidad con vendors antiguos.
    """
    return make_driver(headless=headless, page_load_timeout=page_load_timeout)

def wait_for_page(driver: webdriver.Chrome, timeout: int = 20) -> None:
    """
    Espera a que document.readyState == 'complete'. Tolerante a pequeños fallos.
    """
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except Exception:
        # No reventamos el flujo si la espera falla.
        pass
    # Pequeño margen para “network idle” aproximado
    time.sleep(0.35)

def go(driver: webdriver.Chrome, url: str, timeout: int = 45, wait: bool = True) -> None:
    """
    Navega a una URL con timeout y, si expira, corta la carga con window.stop().
    """
    try:
        try:
            driver.set_page_load_timeout(timeout)
        except Exception:
            pass
        driver.get(url)
    except TimeoutException:
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
    if wait:
        wait_for_page(driver)

__all__ = [
    "make_driver",
    "start_driver",     # <- alias para compatibilidad
    "wait_for_page",
    "go",
]
