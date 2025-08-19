import os
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client

# =========================
# Configuración Twilio
# =========================
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
WHATSAPP_FROM = "whatsapp:+14155238886"
WHATSAPP_TO = "whatsapp:+5214492343676"

# =========================
# Usuarios
# =========================
PAGAQUI_USER = os.getenv("PAGAQUI_USER")
PAGAQUI_PASS = os.getenv("PAGAQUI_PASS")
RECARGAQUI_USER = os.getenv("RECARGAQUI_USER")
RECARGAQUI_PASS = os.getenv("RECARGAQUI_PASS")

# =========================
# Parámetros
# =========================
SALDO_INTENTOS = 3
CICLOS_REINTENTO = 3
CRITICO = 4000
CRITICO_BAIT = 1500

# =========================
# Utilidades
# =========================
def enviar_whatsapp(mensaje: str):
    try:
        if not (TWILIO_SID and TWILIO_TOKEN):
            print("Twilio SID/TOKEN no configurados; no se envía WhatsApp.")
            return
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        message = client.messages.create(body=mensaje, from_=WHATSAPP_FROM, to=WHATSAPP_TO)
        print("Mensaje enviado:", message.sid)
    except Exception as e:
        print(f"Error enviando WhatsApp: {e}")

def _parse_monto(s: str):
    try:
        return float(s.replace("$", "").replace(",", "").replace(" ", "").strip())
    except Exception:
        return None

def _esperar_estable(page, timeout_ms=20000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeout:
        page.wait_for_timeout(1500)

# =========================
# Pagaqui
# =========================
def obtener_saldo_pagaqui():
    for intento in range(1, SALDO_INTENTOS + 1):
        print(f"Intento de consulta de saldo Pagaqui: {intento}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                # 1) Login
                page.goto("https://www.pagaqui.com.mx/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector("#username", timeout=20000)
                page.fill("#username", PAGAQUI_USER or "")
                page.fill("#password", PAGAQUI_PASS or "")

                try:
                    page.click("#btnEntrar", timeout=5000)
                except Exception:
                    page.press("#password", "Enter")
                _esperar_estable(page)

                # forcelogout
                if page.is_visible("#forcelogout") or page.is_visible("input[name='forcelogout']"):
                    print("Sesión previa detectada: forzando cierre...")
                    try:
                        page.check("#forcelogout")
                    except Exception:
                        page.check("input[name='forcelogout']")
                    page.fill("#username", PAGAQUI_USER or "")
                    page.fill("#password", PAGAQUI_PASS or "")
                    page.click("#btnEntrar")
                    _esperar_estable(page)

                # 2) Abrir Administración → Información de cuenta
                try:
                    admin_btn = page.locator("a.nav-link.dropdown-toggle", has_text="Administración")
                    if admin_btn.count():
                        admin_btn.first.click()
                        page.wait_for_timeout(500)
                    if page.is_visible("a:has-text('Información de cuenta')"):
                        page.click("a:has-text('Información de cuenta')")
                        _esperar_estable(page)
                except Exception:
                    pass

                # 3) Buscar fila "Saldo Final" → columna ABONOS
                xpath = (
                    "//div[contains(@class,'row')]"
                    "[.//div[contains(@class,'col-md-6') and normalize-space()='Saldo Final']]"
                    "//div[contains(@class,'col-md-3') and contains(@class,'col-xs-6')]"
                    "[.//span[contains(normalize-space(),'ABONOS')]]"
                )
                loc = page.locator(f"xpath={xpath}")
                saldo = None
                if loc.count():
                    texto = loc.first.inner_text(timeout=5000)
                    m = re.search(r"\$[\s0-9,\.]+", texto)
                    if m:
                        saldo = _parse_monto(m.group(0))

                browser.close()

                if saldo is not None:
                    print(f"Saldo actual Pagaqui: {saldo}")
                    return saldo
                else:
                    print("No se encontró el Saldo Final en ABONOS.")
        except Exception as e:
            print(f"Error en Pagaqui: {e}")
        time.sleep(4)
    return None

# =========================
# Recargaqui (BAIT)
# =========================
def obtener_saldo_recargaqui():
    for intento in range(1, SALDO_INTENTOS + 1):
        print(f"Intento de consulta de saldo Recargaqui: {intento}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto("https://recargaqui.com.mx/Login.aspx", wait_until="domcontentloaded", timeout=30000)

                # Frame de login
                frame = next((f for f in page.frames if "Login.aspx" in (f.url or "")), None)
                if not frame:
                    print("No se encontró el frame del login.")
                    browser.close()
                    return None

                frame.fill('input[name="username"]', RECARGAQUI_USER or "")
                frame.fill('input[name="password"]', RECARGAQUI_PASS or "")
                try:
                    frame.click('input[type="submit"]')
                except Exception:
                    frame.press('input[name="password"]', "Enter")
                page.wait_for_timeout(2500)

                # forcelogout
                if frame.is_visible('input[name="forcelogout"]'):
                    frame.check('input[name="forcelogout"]')
                    frame.fill('input[name="username"]', RECARGAQUI_USER or "")
                    frame.fill('input[name="password"]', RECARGAQUI_PASS or "")
                    frame.click('input[type="submit"]')
                    page.wait_for_timeout(2500)

                # Ir al home VTAE
                page.goto("https://recargaqui.com.mx/home.aspx")
                page.wait_for_selector('table.mGrid', timeout=25000)

                saldo_bait = None
                for fila in page.query_selector_all('table.mGrid > tbody > tr'):
                    celdas = fila.query_selector_all('td')
                    if len(celdas) >= 6 and (celdas[0].inner_text() or "").strip().upper() == "BAIT":
                        saldo_bait = _parse_monto(celdas[-1].inner_text() or "")
                        break

                browser.close()
                return saldo_bait
        except Exception as e:
            print(f"Error en Recargaqui: {e}")
        time.sleep(4)
    return None

# =========================
# Ciclo general
# =========================
def ciclo_consulta():
    return obtener_saldo_pagaqui(), obtener_saldo_recargaqui()

# =========================
# Main
# =========================
if __name__ == "__main__":
    for ciclo in range(1, CICLOS_REINTENTO + 1):
        print(f"\n===== CICLO GENERAL DE CONSULTA #{ciclo} =====")
        saldo_pagaqui, saldo_bait = ciclo_consulta()

        if saldo_pagaqui is not None and saldo_bait is not None:
            print(f"Pagaqui: {saldo_pagaqui}, BAIT: {saldo_bait}")
            criticos = []
            if saldo_pagaqui < CRITICO:
                criticos.append(f"- Pagaqui: ${saldo_pagaqui:,.2f}")
            if saldo_bait < CRITICO_BAIT:
                criticos.append(f"- Recargaqui/BAIT: ${saldo_bait:,.2f}")
            if criticos:
                enviar_whatsapp("⚠️ *Saldo bajo o crítico:*\n" + "\n".join(criticos))
            break
        else:
            if ciclo == CICLOS_REINTENTO:
                enviar_whatsapp("⚠️ No se pudo consultar uno o ambos saldos tras varios intentos.")
                exit(1)
            print("Reintentando en 10s...")
            time.sleep(10)
