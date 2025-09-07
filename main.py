# -*- coding: utf-8 -*-
import os
import re
import time
import re as _re_mod
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client

# ===================== Configuración =====================
# Twilio
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
WHATSAPP_FROM = "whatsapp:+14155238886"
WHATSAPP_TO = "whatsapp:+5214492343676"

# Credenciales
PAGAQUI_USER = os.getenv("PAGAQUI_USER")
PAGAQUI_PASS = os.getenv("PAGAQUI_PASS")
RECARGAQUI_USER = os.getenv("RECARGAQUI_USER")
RECARGAQUI_PASS = os.getenv("RECARGAQUI_PASS")

# Control de reintentos
SALDO_INTENTOS = 3
CICLOS_REINTENTO = 3

# Umbrales críticos separados
CRITICO_PAGAQUI = 3000
CRITICO_BAIT = 1500

# ===================== Utilidades de selectores =====================
USERNAME_SELECTORS = [
    "#username", "input[name='username']",
    "input#UserName",
    "input[id*='user' i]",  # heurística
    "input[name*='user' i]"
]
PASSWORD_SELECTORS = [
    "#password", "#psw", "input[name='password']",
    "input#Password",
    "input[id*='pass' i]",  # heurística
    "input[name*='pass' i]"
]

def _find_in_page_or_frames(page, selectors, timeout=20000):
    """
    Devuelve (target_context, locator, selector_usado) para el primer selector encontrado con state='attached'
    en la página o en cualquier iframe. Lanza PlaywrightTimeout si no aparece a tiempo.
    """
    deadline = time.time() + (timeout / 1000.0)

    def _try_in_target(target):
        for css in selectors:
            try:
                loc = target.locator(css)
                if loc.count() > 0:
                    try:
                        loc.wait_for(state="attached", timeout=1000)
                        return target, loc, css
                    except Exception:
                        pass
            except Exception:
                pass
        return None

    while time.time() < deadline:
        # 1) página
        found = _try_in_target(page)
        if found:
            return found
        # 2) iframes
        for fr in page.frames:
            found = _try_in_target(fr)
            if found:
                return found
        time.sleep(0.2)

    raise PlaywrightTimeout(f"No se encontró ninguno de {selectors} (timeout {timeout} ms)")

def _safe_type(loc, text):
    """
    Tipeo robusto: click -> Ctrl+A -> type (con pequeño delay). Útil cuando el input limpia con onfocus.
    """
    loc.click()
    try:
        loc.press("Control+A")
    except Exception:
        pass
    loc.type(text, delay=20)

def _first_present_locator(target, selectors):
    """
    Devuelve el primer locator existente (count>0) entre 'selectors' dentro de 'target', o None.
    """
    for sel in selectors:
        try:
            loc = target.locator(sel)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass
    return None

def _screenshot(page, prefix):
    try:
        path = f"{prefix}_{int(time.time())}.png"
        page.screenshot(path=path, full_page=True)
        print(f"Captura guardada: {path}")
    except Exception as e:
        print(f"No se pudo guardar captura: {e}")

# ===================== WhatsApp =====================
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

# ===================== Parser de moneda (Recargaqui) =====================
_CURRENCY_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")
def _to_float(texto: str):
    if not texto:
        return None
    t = texto.replace("\xa0", " ").replace("$", " ").strip()
    m = _CURRENCY_RE.search(t)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:
        return None

# ===================== Pagaqui =====================
def _login_pagaqui(page):
    """
    Login robusto en Pagaqui: localiza inputs en página o iframes, maneja onfocus y botón de entrar.
    """
    page.goto("https://www.pagaqui.com.mx", wait_until="domcontentloaded")

    # Si el login no está directamente, intenta un enlace de acceso
    try:
        acc = page.locator("a[href*='Acceso'], a[href*='Login'], a:has-text('Acceso'), a:has-text('Entrar')")
        if acc.count() > 0:
            acc.first.click()
            page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass

    try:
        tgt_user, user_loc, used_user = _find_in_page_or_frames(page, USERNAME_SELECTORS, timeout=20000)
        tgt_pass, pass_loc, used_pass = _find_in_page_or_frames(page, PASSWORD_SELECTORS, timeout=20000)
    except PlaywrightTimeout:
        _screenshot(page, "pagaqui_login_timeout")
        raise

    _safe_type(user_loc, PAGAQUI_USER)
    _safe_type(pass_loc, PAGAQUI_PASS)

    # Botón entrar
    btn = _first_present_locator(
        tgt_user,
        ["#btnEntrar", "button#btnEntrar", "input[type='submit'][value*='Entrar' i]",
         "button:has-text('Entrar')", "button:has-text('Ingresar')", "input[type='submit']"]
    )
    if not btn:
        _screenshot(page, "pagaqui_btn_timeout")
        raise RuntimeError("No se encontró el botón para iniciar sesión en Pagaqui.")

    btn.click()
    page.wait_for_load_state("domcontentloaded")
    time.sleep(2)

    # Checkbox de sesión activa (si aparece)
    for sel in ["#forcelogout", "input[name='forcelogout']"]:
        try:
            fl = tgt_user.locator(sel)
            if fl.count() > 0:
                print("Sesión activa detectada, forzando logout...")
                fl.check()
                _safe_type(user_loc, PAGAQUI_USER)
                _safe_type(pass_loc, PAGAQUI_PASS)
                btn.click()
                page.wait_for_load_state("domcontentloaded")
                time.sleep(2)
                break
        except Exception:
            pass

def _navegar_saldo_pagaqui(page):
    """
    Navega al área de 'Información de cuenta' y extrae 'Saldo Final'.
    """
    # Menú Administración -> Información de cuenta
    page.wait_for_selector('a.nav-link.dropdown-toggle', timeout=20000)
    nav_links = page.locator('a.nav-link.dropdown-toggle')
    clicked = False
    for i in range(min(nav_links.count(), 10)):
        nav = nav_links.nth(i)
        try:
            if "Administración" in (nav.inner_text() or ""):
                nav.click()
                clicked = True
                break
        except Exception:
            pass
    if not clicked:
        # fallback: abre el możulo de cuenta si hay enlace directo
        try:
            page.click("a[href*='InfoCuenta'], a#ctl00_InfoCuentaLink", timeout=10000)
        except Exception:
            pass

    time.sleep(1.2)
    try:
        page.click('a#ctl00_InfoCuentaLink', timeout=10000)
    except Exception:
        # intenta selector alterno
        try:
            page.click("a[href*='InfoCuenta']", timeout=10000)
        except Exception:
            _screenshot(page, "pagaqui_info_link_fail")
            raise

    page.wait_for_load_state('networkidle')
    time.sleep(3)

    # Leer 'Saldo Final' desde divs
    filas = page.query_selector_all('div.row')
    for fila in filas:
        try:
            cols = fila.query_selector_all('div')
            if len(cols) >= 2 and "Saldo Final" in (cols[0].inner_text() or ""):
                abonos = cols[1].inner_text() or ""
                if "$" in abonos:
                    saldo = abonos.split("$")[1].replace(",", "").strip()
                    return float(saldo)
        except Exception:
            continue

    # fallback: buscar por texto
    try:
        possible = page.locator("text=Saldo Final")
        if possible.count() > 0:
            container = possible.first.locator("xpath=..")
            texto = container.inner_text()
            m = _CURRENCY_RE.search(texto or "")
            if m:
                return float(m.group(0).replace(",", ""))
    except Exception:
        pass

    _screenshot(page, "pagaqui_parse_fail")
    return None

def obtener_saldo_pagaqui():
    for intento in range(1, SALDO_INTENTOS + 1):
        print(f"Intento de consulta de saldo Pagaqui: {intento}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                try:
                    _login_pagaqui(page)
                    saldo = _navegar_saldo_pagaqui(page)
                    if saldo is not None:
                        print(f"Saldo actual Pagaqui: {saldo}")
                        return saldo
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass
                    try:
                        browser.close()
                    except Exception:
                        pass
        except PlaywrightTimeout as e:
            print(f"Timeout playwright: {e}")
        except Exception as e:
            print(f"Error playwright: {e}")
        time.sleep(4)
    return None

# ===================== Recargaqui =====================
def obtener_saldo_recargaqui():
    for intento in range(1, SALDO_INTENTOS + 1):
        print(f"Intento de consulta de saldo Recargaqui: {intento}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"]
                )
                context = browser.new_context(
                    locale="es-MX",
                    user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/120.0.0.0 Safari/537.36")
                )
                page = context.new_page()
                try:
                    # === LOGIN (robusto) ===
                    page.goto("https://recargaquiws.com.mx/login.aspx", wait_until="domcontentloaded")
                    try:
                        _, user_loc, _ = _find_in_page_or_frames(page, USERNAME_SELECTORS, timeout=15000)
                        _, pass_loc, _ = _find_in_page_or_frames(page, PASSWORD_SELECTORS, timeout=15000)
                    except PlaywrightTimeout:
                        _screenshot(page, "recargaqui_login_timeout")
                        raise

                    _safe_type(user_loc, RECARGAQUI_USER)
                    _safe_type(pass_loc, RECARGAQUI_PASS)

                    # Force logout (si existe)
                    for sel in ["#forcelogout", "input[name='forcelogout']"]:
                        try:
                            fl = page.locator(sel)
                            if fl.count() > 0:
                                fl.check()
                                break
                        except Exception:
                            pass

                    # Botón entrar
                    btn = _first_present_locator(page, ["input#entrar", "button:has-text('Entrar')", "input[type='submit']"])
                    if not btn:
                        _screenshot(page, "recargaqui_btn_timeout")
                        raise RuntimeError("No se encontró el botón de 'Entrar' en Recargaqui.")
                    btn.click()

                    # Aterrizar en home
                    try:
                        page.wait_for_url(_re_mod.compile(r"/home\.aspx$", _re_mod.I), timeout=15000)
                    except PlaywrightTimeout:
                        page.goto("https://recargaquiws.com.mx/home.aspx", wait_until="domcontentloaded")
                    page.wait_for_load_state('networkidle', timeout=30000)

                    # === Tabla de saldos ===
                    try:
                        page.wait_for_selector("table.mGrid", state="attached", timeout=35000)
                    except PlaywrightTimeout:
                        page.reload(wait_until="domcontentloaded")
                        page.wait_for_load_state('networkidle', timeout=20000)
                        page.wait_for_selector("table.mGrid", state="attached", timeout=20000)

                    filas = page.evaluate(
                        """() => Array.from(document.querySelectorAll("table.mGrid tr[align='right']"))
                            .map(tr => Array.from(tr.querySelectorAll("td")).map(td => td.innerText.trim()))"""
                    )

                    saldo_bait = None
                    if filas:
                        for celdas in filas:
                            if not celdas:
                                continue
                            nombre = (celdas[0] or "").strip().upper()
                            if nombre == "BAIT":
                                saldo_txt = (celdas[-1] or "").strip()
                                saldo_bait = _to_float(saldo_txt)
                                print(f"Saldo actual BAIT (parseado): {saldo_bait}  (texto='{saldo_txt}')")
                                break
                    else:
                        # Fallback por locators
                        page.wait_for_selector("table.mGrid tr[align='right']", state="attached", timeout=15000)
                        loc_filas = page.query_selector_all("table.mGrid tr[align='right']")
                        for fila in loc_filas:
                            celdas = [(td.inner_text() or "").strip() for td in fila.query_selector_all("td")]
                            if not celdas:
                                continue
                            if celdas[0].strip().upper() == "BAIT":
                                saldo_bait = _to_float((celdas[-1] or "").strip())
                                print(f"Saldo actual BAIT (parseado): {saldo_bait}")
                                break

                    if saldo_bait is None:
                        print("No se encontró la fila de BAIT en la tabla de saldos.")
                    return saldo_bait

                finally:
                    # Logout y cierres dentro del with
                    try:
                        page.goto("https://recargaquiws.com.mx/logout.aspx", wait_until="domcontentloaded", timeout=10000)
                        print("Sesión cerrada correctamente en Recargaqui.")
                    except Exception as e:
                        print(f"No se pudo cerrar sesión: {e}")
                    try:
                        context.close()
                    except Exception:
                        pass
                    try:
                        browser.close()
                    except Exception:
                        pass

        except PlaywrightTimeout as e:
            print(f"Timeout playwright: {e}")
        except Exception as e:
            print(f"Error playwright: {e}")

        time.sleep(4)

    return None

# ===================== Orquestación =====================
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
            if saldo_pagaqui < CRITICO_PAGAQUI:
                criticos.append(f"- Pagaqui: ${saldo_pagaqui:,.2f}")
            if saldo_bait < CRITICO_BAIT:
                criticos.append(f"- Recargaqui/BAIT: ${saldo_bait:,.2f}")

            if criticos:
                mensaje = ("⚠️ *Saldo bajo o crítico detectado:*\n"
                           + "\n".join(criticos)
                           + "\n¡Revisa tu plataforma y recarga si es necesario!")
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
                    msj += "\n- No se pudo obtener el saldo de *Pagaqui* tras varios intentos."
                    if saldo_bait is not None:
                        msj += f"\n- Saldo BAIT: ${saldo_bait:,.2f} (no urgente, solo informativo)"
                elif falla_bait:
                    msj += "\n- No se pudo obtener el saldo de *Recargaqui/BAIT* tras varios intentos."
                    if saldo_pagaqui is not None:
                        msj += f"\n- Saldo Pagaqui: ${saldo_pagaqui:,.2f} (no urgente, solo informativo)"
                enviar_whatsapp(msj)
                exit(1)
            else:
                print(f"Reintentando ciclo completo en 10 segundos... (Falla pagaqui={falla_pagaqui}, falla bait={falla_bait})\n")
                time.sleep(10)
