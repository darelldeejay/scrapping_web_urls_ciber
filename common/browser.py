# -*- coding: utf-8 -*-
from __future__ import annotations
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

def make_driver(headless: bool = True, page_load_timeout: int = 60) -> webdriver.Chrome:
    """
    Crea un Chrome headless robusto para GitHub Actions usando Selenium Manager.
    No requiere que Chrome/Chromedriver estén preinstalados: los descarga automáticamente.
    """
    opts = Options()
    if headless:
        # 'new' es más estable en CI modernos
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--window-size=1365,1024")
    # User-Agent opcional (algunos vendors son sensibles)
    opts.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=opts)  # Selenium Manager resuelve binarios
    try:
        driver.set_page_load_timeout(page_load_timeout)
        driver.set_script_timeout(30)
        driver.implicitly_wait(0)
    except Exception:
        pass
    return driver
