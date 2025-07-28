import os
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client

TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
WHATSAPP_FROM = "whatsapp:+14155238886"  # Twilio Sandbox
WHATSAPP_TO = "whatsapp:+5214492343676"  # Cambia si necesitas

USUARIO = os.getenv("PAGAQUI_USER")
PASSWORD = os.getenv("PAGAQUI_PASS")
SALDO_INTENTOS = 3

def enviar_whatsapp(saldo):
    mensaje = f"⚠️ Saldo bajo o crítico en Pagaqui: ${saldo:,.2f}\n¡Revisa tu plataforma y recarga si es necesario!"
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

def obtener_saldo():
    for intento in range(1, SALDO_INTENTOS + 1):
        print(f"Intento de consulta de saldo: {intento}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto("https://www.pagaqui.com.mx/")
                page.wait_for_selector('input[name="username"]', timeout=20000)

                # Login
                page.fill('input[name="username"]', USUARIO)
                page.fill('input[name="password"]', PASSWORD)
                page.click('input[name="entrar"]')
                time.sleep(3)

                # Si aparece checkbox de logout forzado
                if page.query_selector('input[name="forcelogout"]'):
                    page.check('input[name="forcelogout"]')
                    page.fill('input[name="username"]', USUARIO)
                    page.fill('input[name="password"]', PASSWORD)
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

if __name__ == "__main__":
    saldo = obtener_saldo()
    if saldo is not None:
        print(f"Saldo detectado: {saldo}")
        if saldo < 4000:
            enviar_whatsapp(saldo)
        else:
            print("Saldo fuera del rango crítico, no se envía WhatsApp.")
    else:
        print("No se pudo obtener saldo tras 3 intentos.")
        enviar_whatsapp("⚠️ *Error*: No se pudo obtener el saldo de Pagaqui tras 3 intentos. Revisa manualmente.")
