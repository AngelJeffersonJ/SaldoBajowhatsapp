import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client

# Twilio Config
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
WHATSAPP_FROM = "whatsapp:+14155238886"  # Twilio Sandbox
WHATSAPP_TO = "whatsapp:+5214492155882"  # Cambia si necesitas

# Pagaqui
PAGAQUI_USER = os.getenv("PAGAQUI_USER")
PAGAQUI_PASS = os.getenv("PAGAQUI_PASS")

# Recargaqui
RECARGAQUI_USER = os.getenv("RECARGAQUI_USER")
RECARGAQUI_PASS = os.getenv("RECARGAQUI_PASS")

SALDO_INTENTOS = 3
CICLOS_REINTENTO = 3

def enviar_whatsapp(mensaje):
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        message = client.messages.create(
            body=mensaje,
            from_=WHATSAPP_FROM,
            to=WHATSAPP_TO
        )
        print("Mensaje enviado:", message.sid)
    except Exception as e:
        print(f"Error enviando WhatsApp: {e}")

def obtener_saldo_pagaqui():
    for intento in range(1, SALDO_INTENTOS + 1):
        print(f"Intento de consulta de saldo Pagaqui: {intento}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto("https://www.pagaqui.com.mx/")
                page.wait_for_selector('input[name="username"]', timeout=20000)
                page.fill('input[name="username"]', PAGAQUI_USER)
                page.fill('input[name="password"]', PAGAQUI_PASS)
                page.click('input[name="entrar"]')
                time.sleep(3)
                if page.query_selector('input[name="forcelogout"]'):
                    page.check('input[name="forcelogout"]')
                    page.fill('input[name="username"]', PAGAQUI_USER)
                    page.fill('input[name="password"]', PAGAQUI_PASS)
                    page.click('input[name="entrar"]')
                    time.sleep(3)
                page.wait_for_selector('a.nav-link.dropdown-toggle', timeout=20000)
                nav_links = page.query_selector_all('a.nav-link.dropdown-toggle')
                for nav in nav_links:
                    if "Administración" in nav.inner_text():
                        nav.click()
                        break
                time.sleep(1.2)
                page.click('a#ctl00_InfoCuentaLink', timeout=10000)
                page.wait_for_load_state('networkidle')
                time.sleep(3)
                filas = page.query_selector_all('div.row')
                for fila in filas:
                    try:
                        cols = fila.query_selector_all('div')
                        if len(cols) >= 2 and "Saldo Final" in cols[0].inner_text():
                            abonos = cols[1].inner_text()
                            if "$" in abonos:
                                saldo = abonos.split("$")[1].replace(",", "").strip()
                                saldo = float(saldo)
                                browser.close()
                                return saldo
                    except Exception:
                        continue
                browser.close()
        except PlaywrightTimeout as e:
            print(f"Timeout playwright: {e}")
        except Exception as e:
            print(f"Error playwright: {e}")
        time.sleep(4)
    return None

def obtener_saldo_recargaqui():
    for intento in range(1, SALDO_INTENTOS + 1):
        print(f"Intento de consulta de saldo Recargaqui: {intento}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, slow_mo=200)
                page = browser.new_page()
                page.goto("https://recargaquiws.com.mx")
                frame = None
                for f in page.frames:
                    if "Login.aspx" in f.url:
                        frame = f
                        break
                if not frame:
                    print("No se encontró el frame del login")
                    browser.close()
                    return None
                frame.wait_for_selector('input[name="username"]', timeout=12000)
                frame.fill('input[name="username"]', RECARGAQUI_USER)
                frame.fill('input[name="password"]', RECARGAQUI_PASS)
                frame.click('input[name="entrar"]')
                page.wait_for_timeout(2500)
                if frame.is_visible('input[name="forcelogout"]'):
                    print("Apareció el checkbox de sesión activa, forzando logout y reintentando login...")
                    frame.check('input[name="forcelogout"]')
                    frame.fill('input[name="username"]', RECARGAQUI_USER)
                    frame.fill('input[name="password"]', RECARGAQUI_PASS)
                    frame.click('input[name="entrar"]')
                    page.wait_for_timeout(2500)
                page.goto("https://recargaquiws.com.mx/home.aspx")
                try:
                    page.wait_for_selector('table.mGrid', timeout=25000)
                except PlaywrightTimeout:
                    print("No se encontró la tabla de saldos, revisa si el login falló.")
                    browser.close()
                    return None
                filas = page.query_selector_all('table.mGrid > tbody > tr')
                saldo_bait = None
                for fila in filas:
                    celdas = fila.query_selector_all('td')
                    if len(celdas) >= 6:
                        nombre = celdas[0].inner_text().strip()
                        if nombre.upper() == "BAIT":
                            saldo_txt = celdas[-1].inner_text().replace("$", "").replace(",", "").strip()
                            try:
                                saldo_bait = float(saldo_txt)
                                print(f"Saldo actual BAIT: {saldo_bait}")
                            except Exception as e:
                                print("Error convirtiendo saldo:", e)
                            break
                browser.close()
                if saldo_bait is None:
                    print("No se encontró la fila de BAIT.")
                return saldo_bait
        except PlaywrightTimeout as e:
            print(f"Timeout playwright: {e}")
        except Exception as e:
            print(f"Error playwright: {e}")
        time.sleep(4)
    return None

def ciclo_consulta():
    saldo_pagaqui = obtener_saldo_pagaqui()
    saldo_bait = obtener_saldo_recargaqui()
    return saldo_pagaqui, saldo_bait

if __name__ == "__main__":
    for ciclo in range(1, CICLOS_REINTENTO + 1):
        print(f"\n===== CICLO GENERAL DE CONSULTA #{ciclo} =====")
        saldo_pagaqui, saldo_bait = ciclo_consulta()
        falla_pagaqui = saldo_pagaqui is None
        falla_bait = saldo_bait is None

        # ---- SOLO UN MENSAJE SEGÚN EL CASO ----
        if not falla_pagaqui and not falla_bait:
            # Ambos disponibles
            mensaje = ""
            if saldo_pagaqui < 4000 or saldo_bait < 4000:
                urgentes = []
                if saldo_pagaqui < 4000:
                    urgentes.append(f"Pagaqui: ${saldo_pagaqui:,.2f}")
                if saldo_bait < 1500:
                    urgentes.append(f"Recargaqui/BAIT: ${saldo_bait:,.2f}")
                mensaje = "⚠️ Saldo bajo o crítico detectado:\n" + "\n".join(urgentes) + "\n¡Revisa tu plataforma y recarga si es necesario!"
            else:
                mensaje = (f"Saldos normales:\nPagaqui: ${saldo_pagaqui:,.2f}\nRecargaqui/BAIT: ${saldo_bait:,.2f}\nNo urge recarga.")
            enviar_whatsapp(mensaje)
            break

        elif not falla_pagaqui and falla_bait:
            # Solo Pagaqui disponible
            mensaje = f"Sólo se pudo consultar saldo de *Pagaqui*:\nSaldo: ${saldo_pagaqui:,.2f}\n(No es urgente, solo informativo)"
            enviar_whatsapp(mensaje)
            break

        elif falla_pagaqui and not falla_bait:
            # Solo Recargaqui disponible
            mensaje = f"Sólo se pudo consultar saldo de *Recargaqui/BAIT*:\nSaldo: ${saldo_bait:,.2f}\n(No es urgente, solo informativo)"
            enviar_whatsapp(mensaje)
            break

        else:
            # Ninguno disponible
            if ciclo == CICLOS_REINTENTO:
                print("No se pudo consultar saldo en ninguna plataforma tras varios intentos.")
            else:
                print(f"Reintentando ciclo completo en 10 segundos... (Falla pagaqui={falla_pagaqui}, falla bait={falla_bait})\n")
                time.sleep(10)
