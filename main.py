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
SALDO_INTENTOS = 3        # intentos internos por portal
CICLOS_REINTENTO = 3      # ciclos generales (ambos portales)
CRITICO = 4000            # umbral Pagaqui
CRITICO_BAIT = 1500       # umbral BAIT Recargaqui

# =========================
# Utilidades
# =========================
def enviar_whatsapp(mensaje: str):
    """Envía mensaje por WhatsApp con Twilio (maneja excepciones)."""
    try:
        if not (TWILIO_SID and TWILIO_TOKEN):
            print("Twilio SID/TOKEN no configurados; no se envía WhatsApp.")
            return
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        message = client.messages.create(
            body=mensaje,
            from_=WHATSAPP_FROM,
            to=WHATSAPP_TO
        )
        print("Mensaje enviado:", message.sid)
    except Exception as e:
        print(f"Error enviando WhatsApp: {e}")

def _extraer_saldo_texto(texto: str):
    """
    Busca montos tipo $12,345.67 o 12345.67.
    Prioriza el que esté cerca de 'Saldo'/'Saldo Final'. Si no, toma el mayor.
    """
    if not texto:
        return None

    # candidatos generales
    montos = re.findall(
        r"\$?\s*([0-9]{1,3}(?:[, ][0-9]{3})*(?:\.[0-9]{2})|\d+\.\d{2})",
        texto
    )
    if not montos:
        return None

    # cerca de 'saldo' / 'saldo final'
    bloques = re.findall(
        r"(?:saldo(?:\s+final)?[^$]{0,120}\$?\s*([0-9]{1,3}(?:[, ][0-9]{3})*(?:\.[0-9]{2})|\d+\.\d{2}))",
        texto,
        flags=re.I
    )

    candidato = None
    if bloques:
        candidato = bloques[0]
    else:
        # fallback: toma el mayor (suele ser el saldo global)
        def as_float(s: str) -> float:
            return float(s.replace(",", "").replace(" ", ""))
        candidato = max(montos, key=lambda s: as_float(s))

    try:
        return float(candidato.replace(",", "").replace(" ", ""))
    except Exception:
        return None

def _esperar_estable(page, timeout_ms=20000):
    """Espera a que la página quede más o menos estable, tolerando sites con peticiones largas."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeout:
        # Algunos sitios no alcanzan networkidle; esperamos un poco.
        page.wait_for_timeout(1500)

# =========================
# Pagaqui
# =========================
def obtener_saldo_pagaqui():
    """
    Login nuevo:
      - #username, #password, #btnEntrar
    Extracción:
      - Busca nodos con 'Saldo' y '$' en la página actual (dashboard).
      - Si no aparece, intenta abrir enlaces comunes de cuenta/administración.
      - Fallback: parsea todo el texto del body.
    """
    for intento in range(1, SALDO_INTENTOS + 1):
        print(f"Intento de consulta de saldo Pagaqui: {intento}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                # 1) Ir al login
                page.goto("https://www.pagaqui.com.mx/", wait_until="domcontentloaded", timeout=30000)

                # 2) Completar credenciales con los NUEVOS selectores
                page.wait_for_selector("#username", timeout=20000)
                page.fill("#username", PAGAQUI_USER or "")
                page.fill("#password", PAGAQUI_PASS or "")

                # 3) Click en el botón nuevo
                hizo_click = False
                try:
                    page.click("#btnEntrar", timeout=5000)
                    hizo_click = True
                except Exception:
                    pass
                if not hizo_click:
                    # Respaldo: enviar Enter en el password
                    try:
                        page.press("#password", "Enter")
                    except Exception:
                        pass

                _esperar_estable(page, timeout_ms=20000)

                # 4) Manejo de "forcelogout" si aparece (nuevo id #forcelogout con fallback por name)
                try:
                    visible_forcelogout = False
                    try:
                        visible_forcelogout = page.is_visible("#forcelogout")
                    except Exception:
                        visible_forcelogout = False
                    if not visible_forcelogout:
                        try:
                            visible_forcelogout = page.is_visible("input[name='forcelogout']")
                        except Exception:
                            visible_forcelogout = False

                    if visible_forcelogout:
                        print("Sesión previa detectada: forzando cierre y reintentando login...")
                        try:
                            page.check("#forcelogout")
                        except Exception:
                            try:
                                page.check("input[name='forcelogout']")
                            except Exception:
                                pass

                        page.fill("#username", PAGAQUI_USER or "")
                        page.fill("#password", PAGAQUI_PASS or "")
                        try:
                            page.click("#btnEntrar", timeout=4000)
                        except Exception:
                            page.press("#password", "Enter")
                        _esperar_estable(page, timeout_ms=20000)
                except Exception:
                    pass

                # 5) Intentar localizar bloques con 'Saldo' y '$'
                candidatos = []
                try:
                    locator = page.locator(
                        "xpath=//*[contains(translate(normalize-space(.), 'SALDO', 'saldo'), 'saldo') and contains(., '$')]"
                    )
                    if locator.count() > 0:
                        candidatos = locator.all_text_contents()
                except Exception:
                    pass

                # 6) Si no hay candidatos, probar rutas comunes a 'Información de cuenta'
                if not candidatos:
                    posibles = [
                        "a:has-text('Administración')",
                        "a#ctl00_InfoCuentaLink",
                        "a:has-text('Mi cuenta')",
                        "a:has-text('Cuenta')",
                        "a:has-text('Información de cuenta')",
                        "a:has-text('Información')",
                    ]
                    for sel in posibles:
                        try:
                            if page.is_visible(sel):
                                page.click(sel, timeout=1500)
                                _esperar_estable(page, timeout_ms=15000)
                                locator = page.locator(
                                    "xpath=//*[contains(translate(normalize-space(.), 'SALDO', 'saldo'), 'saldo') and contains(., '$')]"
                                )
                                if locator.count() > 0:
                                    candidatos = locator.all_text_contents()
                                    break
                        except Exception:
                            continue

                # 7) Parseo del saldo
                saldo = None
                if candidatos:
                    joined = "\n".join(candidatos)
                    saldo = _extraer_saldo_texto(joined)

                if saldo is None:
                    try:
                        full_text = page.inner_text("body", timeout=6000)
                        saldo = _extraer_saldo_texto(full_text)
                    except Exception:
                        pass

                browser.close()

                if saldo is not None:
                    print(f"Saldo actual Pagaqui (parseado): {saldo}")
                    return saldo
                else:
                    print("No se pudo parsear el saldo en Pagaqui.")
        except PlaywrightTimeout as e:
            print(f"Timeout en Pagaqui: {e}")
        except Exception as e:
            print(f"Error en Pagaqui: {e}")

        # Espera antes del siguiente intento interno
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
                browser = p.chromium.launch(headless=True, slow_mo=200)
                page = browser.new_page()
                page.goto("https://recargaqui.com.mx", wait_until="domcontentloaded", timeout=30000)

                # Buscar frame de Login.aspx
                frame = None
                for f in page.frames:
                    if "Login.aspx" in (f.url or ""):
                        frame = f
                        break
                if not frame:
                    print("No se encontró el frame del login de Recargaqui.")
                    browser.close()
                    return None

                frame.wait_for_selector('input[name="username"]', timeout=12000)
                frame.fill('input[name="username"]', RECARGAQUI_USER or "")
                frame.fill('input[name="password"]', RECARGAQUI_PASS or "")
                # Botón de submit (varias opciones)
                try:
                    frame.click('input[type="submit"]', timeout=4000)
                except Exception:
                    try:
                        frame.click('input[name="entrar"]', timeout=2000)
                    except Exception:
                        try:
                            frame.press('input[name="password"]', "Enter")
                        except Exception:
                            pass
                page.wait_for_timeout(2500)

                # forcelogout si aparece
                try:
                    if frame.is_visible('input[name="forcelogout"]'):
                        print("Sesión previa en Recargaqui: forzando cierre y reintentando login...")
                        frame.check('input[name="forcelogout"]')
                        frame.fill('input[name="username"]', RECARGAQUI_USER or "")
                        frame.fill('input[name="password"]', RECARGAQUI_PASS or "")
                        try:
                            frame.click('input[type="submit"]', timeout=3000)
                        except Exception:
                            try:
                                frame.click('input[name="entrar"]', timeout=2000)
                            except Exception:
                                frame.press('input[name="password"]', "Enter")
                        page.wait_for_timeout(2500)
                except Exception:
                    pass

                # Ir al home de VTAE donde está la tabla
                page.goto("https://recargaqui.com.mx/home.aspx")
                try:
                    page.wait_for_selector('table.mGrid', timeout=25000)
                except PlaywrightTimeout:
                    print("No se encontró la tabla de saldos en Recargaqui. ¿Falló el login?")
                    browser.close()
                    return None

                filas = page.query_selector_all('table.mGrid > tbody > tr')
                saldo_bait = None
                for fila in filas:
                    celdas = fila.query_selector_all('td')
                    if len(celdas) >= 6:
                        nombre = (celdas[0].inner_text() or "").strip()
                        if nombre.upper() == "BAIT":
                            saldo_txt = (celdas[-1].inner_text() or "").replace("$", "").replace(",", "").strip()
                            try:
                                saldo_bait = float(saldo_txt)
                                print(f"Saldo actual BAIT: {saldo_bait}")
                            except Exception as e:
                                print("Error convirtiendo saldo BAIT:", e)
                            break

                browser.close()
                if saldo_bait is None:
                    print("No se encontró la fila de BAIT en Recargaqui.")
                return saldo_bait

        except PlaywrightTimeout as e:
            print(f"Timeout en Recargaqui: {e}")
        except Exception as e:
            print(f"Error en Recargaqui: {e}")

        time.sleep(4)

    return None

# =========================
# Ciclo general
# =========================
def ciclo_consulta():
    saldo_pagaqui = obtener_saldo_pagaqui()
    saldo_bait = obtener_saldo_recargaqui()
    return saldo_pagaqui, saldo_bait

# =========================
# Main
# =========================
if __name__ == "__main__":
    for ciclo in range(1, CICLOS_REINTENTO + 1):
        print(f"\n===== CICLO GENERAL DE CONSULTA #{ciclo} =====")
        saldo_pagaqui, saldo_bait = ciclo_consulta()

        falla_pagaqui = saldo_pagaqui is None
        falla_bait = saldo_bait is None

        # Ambos OK
        if not falla_pagaqui and not falla_bait:
            print("\n--- Ambos saldos consultados exitosamente ---")
            print(f"Saldo Pagaqui: {saldo_pagaqui}")
            print(f"Saldo BAIT: {saldo_bait}")

            criticos = []
            if saldo_pagaqui < CRITICO:
                criticos.append(f"- Pagaqui: ${saldo_pagaqui:,.2f}")
            if saldo_bait < CRITICO_BAIT:
                criticos.append(f"- Recargaqui/BAIT: ${saldo_bait:,.2f}")

            if criticos:
                mensaje = "⚠️ *Saldo bajo o crítico detectado:*\n" + "\n".join(criticos) + "\n¡Revisa tu plataforma y recarga si es necesario!"
                enviar_whatsapp(mensaje)
            else:
                print("Ningún saldo crítico, no se envía WhatsApp.")
            break

        # Alguno falló
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
                raise SystemExit(1)
            else:
                print(f"Reintentando ciclo completo en 10 segundos... (Falla pagaqui={falla_pagaqui}, falla bait={falla_bait})\n")
                time.sleep(10)


