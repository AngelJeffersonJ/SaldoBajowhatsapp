import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client

# === Configuración de números fijos ===
WHATSAPP_FROM = "whatsapp:+14155238886"    # Twilio Sandbox, NO poner como secreto
WHATSAPP_TO = "whatsapp:+5214492155882"    # Número real, NO poner como secreto

SALDO_UMBRAL_BAJO = 3000
SALDO_UMBRAL_RIESGO = 4000

def enviar_whatsapp(msg):
    TWILIO_SID = os.environ["TWILIO_SID"]
    TWILIO_TOKEN = os.environ["TWILIO_TOKEN"]
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    message = client.messages.create(
        body=msg,
        from_=WHATSAPP_FROM,
        to=WHATSAPP_TO
    )
    print("Mensaje enviado:", message.sid)

def revisar_pagaqui():
    USUARIO = os.environ["PAGAQUI_USER"]
    PASSWORD = os.environ["PAGAQUI_PASS"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.pagaqui.com.mx/")
        page.wait_for_selector('input[name="username"]', timeout=15000)
        page.fill('input[name="username"]', USUARIO)
        page.fill('input[name="password"]', PASSWORD)
        page.click('input[name="entrar"]')
        time.sleep(3)

        # Forzar logout si hay checkbox
        intentos = 0
        while page.query_selector('input[name="forcelogout"]') and intentos < 2:
            page.check('input[name="forcelogout"]')
            page.fill('input[name="username"]', USUARIO)
            page.fill('input[name="password"]', PASSWORD)
            page.click('input[name="entrar"]')
            time.sleep(3)
            intentos += 1

        try:
            page.wait_for_selector('a.nav-link.dropdown-toggle', timeout=15000)
        except PlaywrightTimeout:
            browser.close()
            return None

        nav_links = page.query_selector_all('a.nav-link.dropdown-toggle')
        for nav in nav_links:
            if "Administración" in nav.inner_text():
                nav.click()
                break
        time.sleep(1.2)
        try:
            page.click('a#ctl00_InfoCuentaLink', timeout=8000)
        except PlaywrightTimeout:
            browser.close()
            return None

        page.wait_for_load_state('networkidle')
        time.sleep(3)

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

def revisar_recargaqui():
    USUARIO = os.environ["RECARGAQUI_USER"]
    PASSWORD = os.environ["RECARGAQUI_PASS"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://recargaquiws.com.mx/")
        page.wait_for_selector('input[name="username"]', timeout=15000)
        page.fill('input[name="username"]', USUARIO)
        page.fill('input[name="password"]', PASSWORD)
        page.click('input[name="entrar"]')
        time.sleep(3)

        # Forzar logout si hay checkbox
        intentos = 0
        while page.query_selector('input[name="forcelogout"]') and intentos < 2:
            page.check('input[name="forcelogout"]')
            page.fill('input[name="username"]', USUARIO)
            page.fill('input[name="password"]', PASSWORD)
            page.click('input[name="entrar"]')
            time.sleep(3)
            intentos += 1

        page.wait_for_load_state('networkidle')
        time.sleep(2)
        # Buscar saldo en fila de "Bait"
        saldo = None
        filas = page.query_selector_all('tr')
        for fila in filas:
            tds = fila.query_selector_all('td')
            if len(tds) >= 6 and tds[0].inner_text().strip().upper() == "BAIT":
                saldo_str = tds[5].inner_text().replace("$", "").replace(",", "").strip()
                try:
                    saldo = float(saldo_str)
                except Exception:
                    saldo = None
                break

        browser.close()
        return saldo

if __name__ == "__main__":
    mensajes = []
    saldo_pagaqui = revisar_pagaqui()
    saldo_recargaqui = revisar_recargaqui()

    if saldo_pagaqui is not None and saldo_pagaqui < SALDO_UMBRAL_RIESGO:
        mensajes.append(f"Saldo Pagaqui bajo: ${saldo_pagaqui:,.2f}")

    if saldo_recargaqui is not None and saldo_recargaqui < SALDO_UMBRAL_RIESGO:
        mensajes.append(f"Saldo Recargaqui bajo: ${saldo_recargaqui:,.2f}")

    if mensajes:
        mensaje_final = "\n".join(mensajes) + "\n¡Revisa tus plataformas!"
        enviar_whatsapp(mensaje_final)
    else:
        print("Todo en orden. Saldo suficiente en ambas plataformas.")
