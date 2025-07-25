import time
import os
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client

# ---- CONFIGURACIÓN DESDE VARIABLES DE ENTORNO (GitHub Secrets) ----
TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN")
WHATSAPP_FROM = os.environ.get("WHATSAPP_FROM")
WHATSAPP_TO = os.environ.get("WHATSAPP_TO")

# ---- LOGIN ----
USUARIO = "multipago"
PASSWORD = "msa131127e24"
SALDO_UMBRAL = 3000

def enviar_whatsapp(saldo):
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    message = client.messages.create(
        body=f"Saldo Pagaqui bajo: ${saldo:,.2f}\n¡Revisa tu plataforma!",
        from_=WHATSAPP_FROM,
        to=WHATSAPP_TO
    )
    print("Mensaje enviado:", message.sid)

def obtener_saldo():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.pagaqui.com.mx/")
        page.wait_for_selector('input[name="username"]', timeout=15000)

        # Primer intento de login
        page.fill('input[name="username"]', USUARIO)
        page.fill('input[name="password"]', PASSWORD)
        page.click('input[name="entrar"]')
        time.sleep(3)

        # Si aparece el checkbox de forzar logout, hay que forzar sesión
        intentos = 0
        while page.query_selector('input[name="forcelogout"]') and intentos < 2:
            print("Forzando logout de sesión previa...")
            page.check('input[name="forcelogout"]')
            page.fill('input[name="username"]', USUARIO)
            page.fill('input[name="password"]', PASSWORD)
            page.click('input[name="entrar"]')
            time.sleep(3)
            intentos += 1

        # Esperar el menú de navegación
        try:
            page.wait_for_selector('a.nav-link.dropdown-toggle', timeout=15000)
        except PlaywrightTimeout:
            print("Error: No cargó el menú de navegación.")
            browser.close()
            return None

        # Abrir menú Administración
        nav_links = page.query_selector_all('a.nav-link.dropdown-toggle')
        found_admin = False
        for nav in nav_links:
            if "Administración" in nav.inner_text():
                nav.click()
                found_admin = True
                break
        if not found_admin:
            print("No se encontró el menú 'Administración'.")
            browser.close()
            return None

        time.sleep(1.2)  # Menú despliegue

        # Click en "Info. Cuenta"
        try:
            page.click('a#ctl00_InfoCuentaLink', timeout=8000)
        except PlaywrightTimeout:
            print("No se encontró el enlace 'Info. Cuenta'.")
            browser.close()
            return None

        page.wait_for_load_state('networkidle')
        time.sleep(3)  # Deja cargar el saldo

        # Buscar el saldo final en la tabla
        filas = page.query_selector_all('div.row')
        saldo_encontrado = None
        for fila in filas:
            try:
                cols = fila.query_selector_all('div')
                if len(cols) >= 2 and "Saldo Final" in cols[0].inner_text():
                    abonos = cols[1].inner_text()
                    if "$" in abonos:
                        saldo = abonos.split("$")[1].replace(",", "").strip()
                        saldo = float(saldo)
                        saldo_encontrado = saldo
                        break
            except Exception:
                continue

        browser.close()
        return saldo_encontrado

if __name__ == "__main__":
    saldo = obtener_saldo()
    print("Saldo detectado:", saldo)
    if saldo is not None and saldo < SALDO_UMBRAL:
        enviar_whatsapp(saldo)
    elif saldo is not None:
        print("Saldo suficiente, no se envía WhatsApp.")
    else:
        print("No se pudo detectar saldo.")
