# -*- coding: utf-8 -*-
from __future__ import annotations

import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from common.config import (
    PAGE_LOAD_TIMEOUT,
    PAGE_READY_TIMEOUT,
    NAV_TIMEOUT,
    SCRIPT_TIMEOUT,
    get_user_agent,
)


def make_driver(headless: bool = True, page_load_timeout: int = PAGE_LOAD_TIMEOUT) -> webdriver.Chrome:
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

    # User-Agent configurable via SCRAPER_UA env var (see common/config.py)
    opts.add_argument(f"--user-agent={get_user_agent()}")

    driver = webdriver.Chrome(options=opts)  # Selenium Manager resuelve binarios compatibles
    try:
        driver.set_page_load_timeout(page_load_timeout)
        driver.set_script_timeout(SCRIPT_TIMEOUT)
        driver.implicitly_wait(0)
    except Exception:
        pass
    return driver

# Compatibility alias for vendors that still import start_driver
def start_driver(headless: bool = True, page_load_timeout: int = PAGE_LOAD_TIMEOUT) -> webdriver.Chrome:
    """
    Alias legacy para compatibilidad con vendors antiguos.
    """
    return make_driver(headless=headless, page_load_timeout=page_load_timeout)

def wait_for_page(driver: webdriver.Chrome, timeout: int = PAGE_READY_TIMEOUT) -> None:
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

def go(driver: webdriver.Chrome, url: str, timeout: int = NAV_TIMEOUT, wait: bool = True) -> None:
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
