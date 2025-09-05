import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client

# Configuración Twilio
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
WHATSAPP_FROM = "whatsapp:+14155238886"
WHATSAPP_TO = "whatsapp:+5214492343676"

# Usuarios
PAGAQUI_USER = os.getenv("PAGAQUI_USER")
PAGAQUI_PASS = os.getenv("PAGAQUI_PASS")
RECARGAQUI_USER = os.getenv("RECARGAQUI_USER")
RECARGAQUI_PASS = os.getenv("RECARGAQUI_PASS")

SALDO_INTENTOS = 3
CICLOS_REINTENTO = 3

CRITICO = 4000

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
                page.goto("https://www.pagaqui.com.mx")

                # === LOGIN ===
                page.wait_for_selector('#username', timeout=20000)
                page.fill('#username', PAGAQUI_USER)

                # Buscar si existe #password o #psw
                if page.query_selector('#password'):
                    page.fill('#password', PAGAQUI_PASS)
                elif page.query_selector('#psw'):
                    page.fill('#psw', PAGAQUI_PASS)
                else:
                    print("No se encontró campo de contraseña (#password o #psw)")
                    browser.close()
                    return None

                page.click('#btnEntrar')
                time.sleep(3)

                # === CHECKBOX DE SESIÓN ACTIVA ===
                if page.query_selector('#forcelogout') or page.query_selector('input[name="forcelogout"]'):
                    print("Sesión activa detectada, forzando logout...")
                    if page.query_selector('#forcelogout'):
                        page.check('#forcelogout')
                    else:
                        page.check('input[name="forcelogout"]')
                    page.fill('#username', PAGAQUI_USER)
                    if page.query_selector('#password'):
                        page.fill('#password', PAGAQUI_PASS)
                    elif page.query_selector('#psw'):
                        page.fill('#psw', PAGAQUI_PASS)
                    page.click('#btnEntrar')
                    time.sleep(3)

                # Menú Administración -> Información de cuenta
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

                # Leer fila "Saldo Final"
                filas = page.query_selector_all('div.row')
                for fila in filas:
                    try:
                        cols = fila.query_selector_all('div')
                        if len(cols) >= 2 and "Saldo Final" in cols[0].inner_text():
                            abonos = cols[1].inner_text()
                            if "$" in abonos:
                                saldo = abonos.split("$")[1].replace(",", "").strip()
                                saldo = float(saldo)
                                print(f"Saldo actual Pagaqui: {saldo}")
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
        browser = None
        context = None
        page = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
                context = browser.new_context(locale="es-MX", user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"))
                page = context.new_page()

                # Login
                page.goto("https://recargaquiws.com.mx/login.aspx", wait_until="domcontentloaded")
                page.wait_for_selector('input[name="username"]', timeout=15000)
                page.fill('input[name="username"]', RECARGAQUI_USER)
                page.fill('input[name="password"]', RECARGAQUI_PASS)
                page.click('input#entrar')

                # Esperar a que cargue (o forzar ir a home)
                try:
                    page.wait_for_url(re.compile(r"/home\.aspx$", re.I), timeout=15000)
                except PlaywrightTimeout:
                    page.goto("https://recargaquiws.com.mx/home.aspx", wait_until="domcontentloaded")

                # Esperar la tabla y sus filas de datos (no dependemos de <tbody>)
                page.wait_for_selector("table.mGrid", timeout=20000)
                page.wait_for_selector("table.mGrid tr[align='right']", timeout=20000)

                # Confirmar que hay filas
                filas = page.query_selector_all("table.mGrid tr[align='right']")
                if not filas:
                    raise PlaywrightTimeout("La tabla de saldos no tiene filas de datos todavía.")

                saldo_bait = None
                for fila in filas:
                    celdas = fila.query_selector_all("td")
                    if not celdas:
                        continue
                    nombre = (celdas[0].inner_text() or "").strip().upper()
                    if nombre == "BAIT":
                        # Última celda es "Saldo Actual" según el HTML
                        saldo_txt = (celdas[-1].inner_text() or "").strip()
                        saldo_bait = _to_float(saldo_txt)
                        print(f"Saldo actual BAIT (parseado): {saldo_bait}  (texto='{saldo_txt}')")
                        break

                if saldo_bait is None:
                    print("No se encontró la fila de BAIT en la tabla de saldos.")

                return saldo_bait

        except PlaywrightTimeout as e:
            print(f"Timeout playwright: {e}")
        except Exception as e:
            print(f"Error playwright: {e}")
        finally:
            # Cerrar sesión siempre que sea posible
            try:
                if page:
                    page.goto("https://recargaquiws.com.mx/logout.aspx", wait_until="domcontentloaded", timeout=10000)
                    print("Sesión cerrada correctamente en Recargaqui.")
            except Exception as e:
                print(f"No se pudo cerrar sesión: {e}")
            try:
                if context:
                    context.close()
            except:
                pass
            try:
                if browser:
                    browser.close()
            except:
                pass

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

        if not falla_pagaqui and not falla_bait:
            print("\n--- Ambos saldos consultados exitosamente ---")
            print(f"Saldo Pagaqui: {saldo_pagaqui}")
            print(f"Saldo BAIT: {saldo_bait}")

            criticos = []
            if saldo_pagaqui < CRITICO:
                criticos.append(f"- Pagaqui: ${saldo_pagaqui:,.2f}")
            if saldo_bait < 1500:
                criticos.append(f"- Recargaqui/BAIT: ${saldo_bait:,.2f}")

            if criticos:
                mensaje = "⚠️ *Saldo bajo o crítico detectado:*\n" + "\n".join(criticos) + "\n¡Revisa tu plataforma y recarga si es necesario!"
                enviar_whatsapp(mensaje)
            else:
                print("Ningún saldo crítico, no se envía WhatsApp.")
            break
        else:
            if ciclo == CICLOS_REINTENTO:
                msj = "⚠️ *Error consulta de saldo:*"
                if falla_pagaqui and falla_bait:
                    msj += "\n- No se pudo obtener el saldo de *Pagaqui* ni *Recargaqui/BAIT* tras varios intentos. Revisa manualmente."
                elif falla_pagaqui:
                    msj += f"\n- No se pudo obtener el saldo de *Pagaqui* tras varios intentos."
                    if saldo_bait is not None:
                        msj += f"\n- Saldo BAIT: ${saldo_bait:,.2f} (no urgente, solo informativo)"
                elif falla_bait:
                    msj += f"\n- No se pudo obtener el saldo de *Recargaqui/BAIT* tras varios intentos."
                    if saldo_pagaqui is not None:
                        msj += f"\n- Saldo Pagaqui: ${saldo_pagaqui:,.2f} (no urgente, solo informativo)"
                enviar_whatsapp(msj)
                exit(1)
            else:
                print(f"Reintentando ciclo completo en 10 segundos... (Falla pagaqui={falla_pagaqui}, falla bait={falla_bait})\n")
                time.sleep(10)












