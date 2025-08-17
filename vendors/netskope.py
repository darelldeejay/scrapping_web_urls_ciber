# vendors/netskope.py
from common.browser import start_driver
from common.notify import send_telegram, send_teams
from common.format import header

# Importa tu main actual si quieres reutilizar funciones;
# o copia aquí las funciones analizar/formatear que ya tienes.
# Para no tocar nada, hacemos un wrapper mínimo:
import main as netskope_impl  # usa tu main.py tal cual

def run():
    driver = start_driver()
    try:
        activos, pasados_15 = netskope_impl.analizar_netskope(driver)  # ya lo tienes
        resumen = netskope_impl.formatear_resumen(activos, pasados_15)
        # prepend header por consistencia (si tu formatear ya lo añade, omite esta línea)
        if not resumen.lstrip().startswith("<b>Netskope"):
            resumen = header("Netskope") + "\n\n" + resumen
        send_telegram(resumen)
        send_teams(resumen)
    finally:
        driver.quit()
