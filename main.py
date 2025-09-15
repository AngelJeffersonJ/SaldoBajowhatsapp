# -*- coding: utf-8 -*-
import os
import re
import time
import unicodedata
import tempfile
import re as _re_mod
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from twilio.rest import Client

# (opcional) cargar .env si lo usas en local
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ===================== Configuración =====================
# Twilio
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
WHATSAPP_FROM = os.getenv("WHATSAPP_FROM", "whatsapp:+14155238886")
WHATSAPP_TO = os.getenv("WHATSAPP_TO", "whatsapp:+5214492343676")

# Credenciales
PAGAQUI_USER = os.getenv("PAGAQUI_USER")
PAGAQUI_PASS = os.getenv("PAGAQUI_PASS")
RECARGAQUI_USER = os.getenv("RECARGAQUI_USER")
RECARGAQUI_PASS = os.getenv("RECARGAQUI_PASS")

# Control de reintentos
SALDO_INTENTOS = int(os.getenv("SALDO_INTENTOS", "3"))
CICLOS_REINTENTO = int(os.getenv("CICLOS_REINTENTO", "3"))

# Umbrales críticos separados
CRITICO_PAGAQUI = float(os.getenv("CRITICO_PAGAQUI", "3000"))
CRITICO_BAIT = float(os.getenv("CRITICO_BAIT", "1500"))

# Debug opcional (1 = volcar HTML si la extracción falla)
DEBUG_DUMP_HTML = os.getenv("DEBUG_DUMP_HTML", "0") == "1"

# ===================== Utilidades de selectores =====================
# Ampliados para cubrir el login real de Recargaqui y Pagaqui
USERNAME_SELECTORS = [
    "#username",
    "input[name='username']",
    "input#UserName",
    "input[id*='user' i]",
    "input[name*='user' i]",
    "input.input.username",
    "input.username",
    "input[class*='username' i]",
    "input[placeholder*='usuario' i]",
    "input[value='Usuario']",
]
PASSWORD_SELECTORS = [
    "#password",
    "#psw",
    "input[name='password']",
    "input#Password",
    "input[id*='pass' i]",
    "input[name*='pass' i]",
    "input.input.password",
    "input.password",
    "input[class*='password' i]",
    "input[placeholder*='contraseña' i]",
    "input[type='password']",
]

def _find_in_page_or_frames(page, selectors, timeout=20000):
    """
    Devuelve (target_context, locator, selector_usado) para el primer selector encontrado
    en la página o en cualquier frame. Reintenta hasta 'timeout'.
    """
    deadline = time.time() + (timeout / 1000.0)

    def _try_in_target(target):
        for css in selectors:
            try:
                loc = target.locator(css).first
                # Espera breve a que aparezca
                loc.wait_for(state="attached", timeout=600)
                return target, loc, css
            except Exception:
                continue
        return None

    while time.time() < deadline:
        # probar página principal
        found = _try_in_target(page)
        if found:
            return found
        # probar frames ya montados
        for fr in page.frames:
            found = _try_in_target(fr)
            if found:
                return found
        time.sleep(0.2)

    raise PlaywrightTimeout(f"No se encontró ninguno de {selectors} (timeout {timeout} ms)")

def _safe_type(loc, text):
    """Click -> Ctrl+A -> type (maneja onfocus que limpia el valor)."""
    loc.click()
    try:
        loc.press("Control+A")
    except Exception:
        pass
    loc.type(text, delay=20)

def _first_present_locator(target, selectors):
    """Devuelve el primer locator existente (count>0) entre 'selectors' o None."""
    for sel in selectors:
        try:
            loc = target.locator(sel)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass
    return None

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

# ===================== Utilidades texto/moneda =====================
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

def _norm(s: str) -> str:
    """minúsculas + sin acentos + trim (para comparar encabezados/valores)."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.strip().lower()

def _norm_laxo(s: str) -> str:
    """normalización más laxa (colapsa espacios)."""
    return " ".join(_norm(s).split())

# ===================== Pagaqui (como estaba) =====================
def _login_pagaqui(page):
    """Login robusto en Pagaqui (maneja forcelogout)."""
    page.goto("https://www.pagaqui.com.mx", wait_until="domcontentloaded")
    try:
        acc = page.locator("a[href*='Acceso'], a[href*='Login'], a:has-text('Acceso'), a:has-text('Entrar')")
        if acc.count() > 0:
            acc.first.click()
            page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass

    tgt_user, user_loc, _ = _find_in_page_or_frames(page, USERNAME_SELECTORS, timeout=20000)
    _, pass_loc, _ = _find_in_page_or_frames(page, PASSWORD_SELECTORS, timeout=20000)

    _safe_type(user_loc, PAGAQUI_USER)
    _safe_type(pass_loc, PAGAQUI_PASS)

    btn = _first_present_locator(
        tgt_user,
        ["#btnEntrar", "button#btnEntrar", "input[type='submit'][value*='Entrar' i]",
         "button:has-text('Entrar')", "button:has-text('Ingresar')", "input[type='submit']"]
    )
    if not btn:
        raise RuntimeError("No se encontró el botón para iniciar sesión en Pagaqui.")

    btn.click()
    page.wait_for_load_state("domcontentloaded")
    time.sleep(2)

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
    """Ir a Información de cuenta y extraer 'Saldo Final'."""
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
        try:
            page.click("a[href*='InfoCuenta'], a#ctl00_InfoCuentaLink", timeout=10000)
        except Exception:
            pass

    time.sleep(1.2)
    try:
        page.click('a#ctl00_InfoCuentaLink', timeout=10000)
    except Exception:
        try:
            page.click("a[href*='InfoCuenta']", timeout=10000)
        except Exception:
            raise

    page.wait_for_load_state('networkidle')
    time.sleep(3)

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
                    try: context.close()
                    except Exception: pass
                    try: browser.close()
                    except Exception: pass
        except PlaywrightTimeout as e:
            print(f"Timeout playwright: {e}")
        except Exception as e:
            print(f"Error playwright: {e}")
        time.sleep(4)
    return None

# ===================== Recargaqui =====================
def _recargaqui_login_and_targets(page):
    """
    Login en Recargaqui y posicionamiento explícito en https://recargaquiws.com.mx/home.aspx.
    Devuelve [page] + frames.
    """
    # 1) Cargar portada (según tu nota el login vive aquí)
    page.goto("https://recargaquiws.com.mx/", wait_until="domcontentloaded")

    # Fallback directo a /login.aspx por si la portada no pinta el form en headless
    try:
        tgt_user, user_loc, _ = _find_in_page_or_frames(page, USERNAME_SELECTORS, timeout=6000)
        _, pass_loc, _ = _find_in_page_or_frames(page, PASSWORD_SELECTORS, timeout=6000)
    except PlaywrightTimeout:
        page.goto("https://recargaquiws.com.mx/login.aspx", wait_until="domcontentloaded")
        tgt_user, user_loc, _ = _find_in_page_or_frames(page, USERNAME_SELECTORS, timeout=15000)
        _, pass_loc, _ = _find_in_page_or_frames(page, PASSWORD_SELECTORS, timeout=15000)

    _safe_type(user_loc, RECARGAQUI_USER)
    _safe_type(pass_loc, RECARGAQUI_PASS)

    # Botón Entrar/Acceder
    btn = _first_present_locator(tgt_user, [
        "input#entrar",
        "button#entrar",
        "button:has-text('Entrar')",
        "button:has-text('Acceder')",
        "input[type='submit']",
        "button[type='submit']",
    ])
    if not btn:
        btn = _first_present_locator(page, [
            "input#entrar",
            "button#entrar",
            "button:has-text('Entrar')",
            "button:has-text('Acceder')",
            "input[type='submit']",
            "button[type='submit']",
        ])
    if not btn:
        raise RuntimeError("No se encontró el botón de 'Entrar/Acceder' en Recargaqui.")
    btn.click()

    # 2) Ir a home.aspx donde está la tabla
    try:
        page.wait_for_url(_re_mod.compile(r"/home\.aspx$", _re_mod.I), timeout=20000)
    except PlaywrightTimeout:
        try:
            page.goto("https://recargaquiws.com.mx/home.aspx", wait_until="domcontentloaded")
        except Exception:
            pass

    # Click explícito a INICIO por texto (como en tu captura)
    try:
        ini = page.locator("a:has-text('INICIO')")
        if ini.count() > 0:
            ini.first.click()
            page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass

    # Esperar a que exista al menos una tabla
    try:
        page.wait_for_selector("table", state="attached", timeout=20000)
    except Exception:
        pass

    return [page] + list(page.frames)

def _extraer_bait_saldo_actual_en_target(target, timeout_ms=45000, interval_ms=400):
    """
    Escanea tablas del 'target' priorizando .mGrid:
      1) Encuentra fila cuyo primer TD sea exactamente 'BAIT' (normalizado).
      2) Detecta la columna 'Saldo Actual'; si no existe, usa la última celda numérica.
    Devuelve float o None.
    """
    deadline = time.time() + timeout_ms / 1000.0
    last_err = None
    saldo_header_keys = ["saldo actual", "saldo_actual", "saldo  actual"]

    def _is_bait_first_cell(row):
        if not row:
            return False
        first = _norm_laxo(row[0])
        return first == "bait"

    while time.time() < deadline:
        try:
            tablas = target.evaluate("""
                () => {
                  const grab = el => (el?.innerText ?? "").trim();
                  const pick = sel => Array.from(document.querySelectorAll(sel));
                  // Prioriza .mGrid; si no hay, toma todas
                  let t = pick("table.mGrid");
                  if (t.length === 0) t = pick("table");
                  return t.map(tbl => {
                    // Headers
                    let headers = [];
                    const thead = tbl.querySelector("thead tr");
                    if (thead) {
                      headers = Array.from(thead.querySelectorAll("th,td")).map(grab);
                    } else {
                      const firstRow = tbl.querySelector("tr");
                      if (firstRow) headers = Array.from(firstRow.querySelectorAll("th,td")).map(grab);
                    }
                    // Body
                    let bodyRows = Array.from(tbl.querySelectorAll("tbody tr"));
                    if (bodyRows.length === 0) {
                      const trs = Array.from(tbl.querySelectorAll("tr"));
                      bodyRows = trs.filter(tr => tr.querySelectorAll("td").length > 0);
                      // si usamos la primera fila como headers, quítala del body
                      const usedFirstAsHeader = !thead && !!tbl.querySelector("tr th");
                      if (usedFirstAsHeader && bodyRows.length > 0) bodyRows = bodyRows.slice(1);
                    }
                    const rows = bodyRows.map(tr => Array.from(tr.querySelectorAll("td")).map(grab));
                    return { headers, rows, isMGrid: tbl.classList.contains("mGrid") };
                  });
                }
            """)

            # Recorre primero las .mGrid
            tablas.sort(key=lambda x: (not x.get("isMGrid", False)))

            for tbl in tablas:
                headers = tbl.get("headers") or []
                rows = tbl.get("rows") or []
                if not rows:
                    continue

                headers_norm = [_norm_laxo(h) for h in headers]

                # Ubica columna por encabezado
                col_idx = None
                for i, h in enumerate(headers_norm):
                    if any(key in h for key in saldo_header_keys):
                        col_idx = i
                        break

                # Busca fila BAIT por igualdad estricta en la primera celda
                fila_bait = None
                for r in rows:
                    if _is_bait_first_cell(r):
                        fila_bait = r
                        break
                # Fallback: buscar "BAIT" en cualquier celda (menos preferido)
                if fila_bait is None:
                    for r in rows:
                        if any(_norm_laxo(c) == "bait" for c in r):
                            fila_bait = r
                            break
                if fila_bait is None:
                    continue

                # Toma celda candidata
                if col_idx is not None and col_idx < len(fila_bait):
                    candidato = fila_bait[col_idx]
                else:
                    # última celda numérica de la fila; si no hay, última celda
                    nums = [c for c in fila_bait if _to_float(c) is not None]
                    candidato = nums[-1] if nums else (fila_bait[-1] if fila_bait else "")

                val = _to_float(candidato)
                if val is not None:
                    print(f"BAIT / Saldo Actual detectado: {val}")
                    return val

        except Exception as e:
            last_err = e

        time.sleep(interval_ms / 1000.0)

    if last_err:
        print(f"[extraer_bait] último error silencioso: {last_err}")

    # Dump de HTML opcional para diagnóstico
    if DEBUG_DUMP_HTML:
        try:
            html = target.content()
            fname = os.path.join(tempfile.gettempdir(), f"recargaqui_debug_{int(time.time())}.html")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[DEBUG] HTML volcado en: {fname}")
        except Exception as e:
            print(f"[DEBUG] No se pudo volcar HTML: {e}")

    return None

def obtener_saldo_recargaqui():
    """
    Busca el 'Saldo Actual' de BAIT en https://recargaquiws.com.mx/home.aspx (sin asumir 'fila 9').
    Escanea página y todos los frames. Hace logout al final.
    """
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
                    targets = _recargaqui_login_and_targets(page)

                    # Debug útil
                    try:
                        print("URL principal:", page.url)
                        print("Frames:", [(fr.name, fr.url) for fr in page.frames])
                    except Exception:
                        pass

                    saldo_bait_actual = None
                    for t in targets:
                        saldo_bait_actual = _extraer_bait_saldo_actual_en_target(t)
                        if saldo_bait_actual is not None:
                            break

                    if saldo_bait_actual is None:
                        print("No se pudo localizar 'BAIT' ni un 'Saldo Actual' numérico en las tablas disponibles.")

                    return saldo_bait_actual

                finally:
                    try:
                        page.goto("https://recargaquiws.com.mx/logout.aspx", wait_until="domcontentloaded", timeout=10000)
                        print("Sesión cerrada correctamente en Recargaqui.")
                    except Exception as e:
                        print(f"No se pudo cerrar sesión: {e}")
                    try: context.close()
                    except Exception: pass
                    try: browser.close()
                    except Exception: pass

        except PlaywrightTimeout as e:
            print(f"Timeout playwright: {e}")
        except Exception as e:
            print(f"Error playwright: {e}")

        time.sleep(4)

    return None

# ===================== Orquestación =====================
def ciclo_consulta():
    saldo_pagaqui = obtener_saldo_pagaqui()
    saldo_bait_actual = obtener_saldo_recargaqui()  # <-- Saldo Actual de BAIT (robusto)
    return saldo_pagaqui, saldo_bait_actual

if __name__ == "__main__":
    for ciclo in range(1, CICLOS_REINTENTO + 1):
        print(f"\n===== CICLO GENERAL DE CONSULTA #{ciclo} =====")
        saldo_pagaqui, saldo_bait = ciclo_consulta()

        falla_pagaqui = saldo_pagaqui is None
        falla_bait = saldo_bait is None

        if not falla_pagaqui and not falla_bait:
            print("\n--- Ambos valores consultados exitosamente ---")
            print(f"Saldo Pagaqui (Saldo Final): {saldo_pagaqui}")
            print(f"BAIT / Saldo Actual: {saldo_bait}")

            criticos = []
            if saldo_pagaqui < CRITICO_PAGAQUI:
                criticos.append(f"- Pagaqui: ${saldo_pagaqui:,.2f}")
            if saldo_bait < CRITICO_BAIT:
                criticos.append(f"- Recargaqui/BAIT (Saldo Actual): ${saldo_bait:,.2f}")

            if criticos:
                mensaje = ("⚠️ *Saldo/valor bajo o crítico detectado:*\n"
                           + "\n".join(criticos)
                           + "\n¡Revisa tu plataforma y recarga si es necesario!")
                enviar_whatsapp(mensaje)
            else:
                print("Ningún valor crítico, no se envía WhatsApp.")
            break
        else:
            if ciclo == CICLOS_REINTENTO:
                msj = "⚠️ *Error de consulta:*"
                if falla_pagaqui and falla_bait:
                    msj += "\n- No se pudo obtener *Pagaqui (Saldo Final)* ni *Recargaqui/BAIT (Saldo Actual)* tras varios intentos. Revisa manualmente."
                elif falla_pagaqui:
                    msj += "\n- No se pudo obtener *Pagaqui (Saldo Final)* tras varios intentos."
                    if saldo_bait is not None:
                        msj += f"\n- BAIT / Saldo Actual: ${saldo_bait:,.2f} (solo informativo)"
                elif falla_bait:
                    msj += "\n- No se pudo obtener *Recargaqui/BAIT (Saldo Actual)* tras varios intentos."
                    if saldo_pagaqui is not None:
                        msj += f"\n- Pagaqui (Saldo Final): ${saldo_pagaqui:,.2f} (solo informativo)"
                enviar_whatsapp(msj)
                exit(1)
            else:
                print(f"Reintentando ciclo completo en 10 segundos... (Falla pagaqui={falla_pagaqui}, falla bait={falla_bait})\n")
                time.sleep(10)
