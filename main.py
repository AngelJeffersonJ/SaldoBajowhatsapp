# -*- coding: utf-8 -*-
import os
import re
import time
import unicodedata
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
SALDO_INTENTOS = int(os.getenv("SALDO_INTENTOS", "3"))
CICLOS_REINTENTO = int(os.getenv("CICLOS_REINTENTO", "3"))

# Umbrales críticos separados
CRITICO_PAGAQUI = float(os.getenv("CRITICO_PAGAQUI", "3000"))
CRITICO_BAIT = float(os.getenv("CRITICO_BAIT", "1500"))

# ===================== Utilidades de selectores =====================
USERNAME_SELECTORS = [
    "#username", "input[name='username']",
    "input#UserName",
    "input[id*='user' i]",
    "input[name*='user' i]"
]
PASSWORD_SELECTORS = [
    "#password", "#psw", "input[name='password']",
    "input#Password",
    "input[id*='pass' i]",
    "input[name*='pass' i]"
]

def _find_in_page_or_frames(page, selectors, timeout=20000):
    """
    Devuelve (target_context, locator, selector_usado) para el primer selector encontrado con state='attached'
    en la página o en cualquier iframe/frame. Lanza PlaywrightTimeout si no aparece a tiempo.
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
        # 1) documento top
        found = _try_in_target(page)
        if found:
            return found
        # 2) todos los frames (Playwright ya devuelve el árbol completo en page.frames)
        for fr in page.frames:
            found = _try_in_target(fr)
            if found:
                return found
        time.sleep(0.2)

    raise PlaywrightTimeout(f"No se encontró ninguno de {selectors} (timeout {timeout} ms)")

def _safe_type(loc, text):
    """Click -> Ctrl+A -> type con pequeño delay (maneja onfocus que limpia)."""
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

# ===================== Helpers tabla Recargaqui =====================
def _poll_table_as_dicts_in(target, timeout_ms=45000, interval_ms=350):
    """
    Lee table.mGrid por JS en 'target' (Page o Frame) y devuelve:
      - headers_norm: lista de headers normalizados (sin acento, minúsculas)
      - rows_dicts: lista de dicts por fila, con claves = headers_norm y valores = texto plano
        Además cada dict trae:
          __first_cell: texto del primer TD
          __first_cell_norm: mismo normalizado
    """
    deadline = time.time() + timeout_ms / 1000.0
    last_err = None
    while time.time() < deadline:
        try:
            data = target.evaluate(
                """() => {
                    const tbl = document.querySelector("table.mGrid");
                    if (!tbl) return {headers_norm: [], rows_dicts: []};
                    const norm = s => (s || "")
                        .trim()
                        .toLowerCase()
                        .normalize('NFD')
                        .replace(/[\\u0300-\\u036f]/g, '');

                    // Headers (thead o fila con th)
                    let ths = Array.from(tbl.querySelectorAll("thead th"));
                    if (ths.length === 0) {
                        const firstHeaderRow = tbl.querySelector("tr.filterHeader, thead tr, tr");
                        if (firstHeaderRow) {
                            ths = Array.from(firstHeaderRow.querySelectorAll("th"));
                        }
                    }
                    const headers_raw = ths.map(th => (th.textContent || "").trim());
                    const headers_norm = headers_raw.map(norm);

                    // Rows (tbody o todos los tr con td)
                    let bodyRows = Array.from(tbl.querySelectorAll("tbody tr"));
                    if (bodyRows.length === 0) {
                        bodyRows = Array.from(tbl.querySelectorAll("tr"))
                          .filter(tr => tr.querySelectorAll("td").length > 0);
                    }

                    const rows_dicts = bodyRows.map(tr => {
                        const tds = Array.from(tr.querySelectorAll("td"));
                        const cells = tds.map(td => (td.textContent || "").trim());
                        const obj = {};
                        headers_norm.forEach((h, i) => { obj[h] = cells[i] || ""; });
                        obj.__first_cell = cells[0] || "";
                        obj.__first_cell_norm = norm(obj.__first_cell);
                        return obj;
                    });

                    return {headers_norm, rows_dicts};
                }"""
            )
            headers_norm = data.get("headers_norm") or []
            rows_dicts = data.get("rows_dicts") or []
            if headers_norm and rows_dicts:
                return headers_norm, rows_dicts
        except Exception as e:
            last_err = e
        time.sleep(interval_ms / 1000.0)
    if last_err:
        print(f"[poll dicts] último error silencioso: {last_err}")
    return [], []

def _extract_recargas_bait_from_html(html: str):
    """
    Fallback leyendo el HTML completo (de un frame/target):
      1) Encabezados del thead (o de la primera fila con <th>).
      2) Índice de la columna 'recargas'.
      3) Fila cuyo primer <td> normalizado sea 'bait'.
      4) Devuelve el valor de esa columna como float.
    """
    try:
        thead = re.search(r"<thead[^>]*>(.*?)</thead>", html, re.S | re.I)
        header_html = thead.group(1) if thead else html
        ths = re.findall(r"<th[^>]*>(.*?)</th>", header_html, re.S | re.I)
        if not ths:
            first_th_row = re.search(r"<tr[^>]*>(?:(?!</tr>).)*?<th[^>]*>.*?</tr>", html, re.S | re.I)
            if first_th_row:
                ths = re.findall(r"<th[^>]*>(.*?)</th>", first_th_row.group(0), re.S | re.I)
        headers = [re.sub(r"<[^>]+>", "", th).strip() for th in ths]
        headers_norm = [_norm(h) for h in headers]
        if not headers_norm:
            return None

        try:
            idx_recargas = headers_norm.index("recargas")
        except ValueError:
            return None

        tbody = re.search(r"<tbody[^>]*>(.*?)</tbody>", html, re.S | re.I)
        if not tbody:
            return None
        tbody_html = tbody.group(1)
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_html, re.S | re.I)
        for row_html in rows:
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S | re.I)
            if not tds:
                continue
            cells_txt = [re.sub(r"<[^>]+>", "", td).strip() for td in tds]
            if not cells_txt:
                continue
            if _norm(cells_txt[0]) == "bait":
                if idx_recargas < len(cells_txt):
                    return _to_float(cells_txt[idx_recargas])
                break
        return None
    except Exception as e:
        print(f"Regex fallback error: {e}")
        return None

# ===================== Pagaqui =====================
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

    try:
        tgt_user, user_loc, _ = _find_in_page_or_frames(page, USERNAME_SELECTORS, timeout=20000)
        _, pass_loc, _ = _find_in_page_or_frames(page, PASSWORD_SELECTORS, timeout=20000)
    except PlaywrightTimeout:
        raise

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
def _recargaqui_login_and_targets(page):
    """
    Hace login en Recargaqui y devuelve la lista de targets donde buscar la tabla:
    [page] + page.frames (frames ya poblados tras el login/home).
    Además, intenta 'nudge' al home.
    """
    # Login
    page.goto("https://recargaquiws.com.mx/login.aspx", wait_until="domcontentloaded")
    tgt_user, user_loc, _ = _find_in_page_or_frames(page, USERNAME_SELECTORS, timeout=15000)
    _, pass_loc, _ = _find_in_page_or_frames(page, PASSWORD_SELECTORS, timeout=15000)

    _safe_type(user_loc, RECARGAQUI_USER)
    _safe_type(pass_loc, RECARGAQUI_PASS)

    # force logout (si existe)
    for sel in ["#forcelogout", "input[name='forcelogout']"]:
        try:
            fl = tgt_user.locator(sel)
            if fl.count() > 0:
                fl.check()
                break
        except Exception:
            pass

    # botón "Entrar" dentro del MISMO target del login
    btn = _first_present_locator(tgt_user, ["input#entrar", "button:has-text('Entrar')", "input[type='submit']"])
    if not btn:
        # fallback al documento top por si el botón está afuera (menos común)
        btn = _first_present_locator(page, ["input#entrar", "button:has-text('Entrar')", "input[type='submit']"])
    if not btn:
        raise RuntimeError("No se encontró el botón de 'Entrar' en Recargaqui.")
    btn.click()

    # Aterrizar en home
    try:
        page.wait_for_url(_re_mod.compile(r"/home\.aspx$", _re_mod.I), timeout=15000)
    except PlaywrightTimeout:
        try:
            page.goto("https://recargaquiws.com.mx/home.aspx", wait_until="domcontentloaded")
        except Exception:
            pass

    # Nudge de inicio para forzar render en algunos setups
    try:
        mi = page.locator("#ctl00_mInicio, a[href='home.aspx']")
        if mi.count() > 0:
            mi.first.click()
            page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass

    targets = [page] + list(page.frames)
    return targets

def _extraer_bait_recargas_en_target(target):
    """
    Intenta extraer BAIT/Recargas en un target (Page o Frame).
    1) DOM por JS (thead + tbody -> dicts)
    2) Fallback: HTML del target
    Devuelve float o None.
    """
    # 1) DOM
    headers_norm, rows_dicts = _poll_table_as_dicts_in(target, timeout_ms=20000, interval_ms=300)
    if headers_norm and rows_dicts and "recargas" in headers_norm:
        for obj in rows_dicts:
            if obj.get("__first_cell_norm") == "bait":
                val = _to_float(obj.get("recargas"))
                if val is not None:
                    print(f"BAIT / Recargas (DOM en frame): {val}")
                    return val

    # 2) HTML fallback (del target)
    try:
        html = target.content()
    except Exception:
        html = ""
    if html:
        val = _extract_recargas_bait_from_html(html)
        if val is not None:
            print(f"BAIT / Recargas (HTML en frame): {val}")
            return val

    return None

def obtener_saldo_recargaqui():
    """
    Devuelve el valor de la COLUMNA 'Recargas' para la FILA 'BAIT' en Recargaqui.
    Recorre documento top y TODOS los frames.
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

                    # Probar en cada target (documento top + frames)
                    saldo_bait_recargas = None
                    for t in targets:
                        saldo_bait_recargas = _extraer_bait_recargas_en_target(t)
                        if saldo_bait_recargas is not None:
                            break

                    if saldo_bait_recargas is None:
                        print("No se encontró la fila 'BAIT' o la columna 'Recargas' (DOM/HTML) en ninguno de los frames.")

                    return saldo_bait_recargas

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
    saldo_bait_recargas = obtener_saldo_recargaqui()
    return saldo_pagaqui, saldo_bait_recargas

if __name__ == "__main__":
    for ciclo in range(1, CICLOS_REINTENTO + 1):
        print(f"\n===== CICLO GENERAL DE CONSULTA #{ciclo} =====")
        saldo_pagaqui, saldo_bait = ciclo_consulta()

        falla_pagaqui = saldo_pagaqui is None
        falla_bait = saldo_bait is None

        if not falla_pagaqui and not falla_bait:
            print("\n--- Ambos valores consultados exitosamente ---")
            print(f"Saldo Pagaqui (Saldo Final): {saldo_pagaqui}")
            print(f"BAIT / Recargas: {saldo_bait}")

            criticos = []
            if saldo_pagaqui < CRITICO_PAGAQUI:
                criticos.append(f"- Pagaqui: ${saldo_pagaqui:,.2f}")
            if saldo_bait < CRITICO_BAIT:
                criticos.append(f"- Recargaqui/BAIT (Recargas): ${saldo_bait:,.2f}")

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
                    msj += "\n- No se pudo obtener *Pagaqui (Saldo Final)* ni *Recargaqui/BAIT (Recargas)* tras varios intentos. Revisa manualmente."
                elif falla_pagaqui:
                    msj += "\n- No se pudo obtener *Pagaqui (Saldo Final)* tras varios intentos."
                    if saldo_bait is not None:
                        msj += f"\n- BAIT / Recargas: ${saldo_bait:,.2f} (solo informativo)"
                elif falla_bait:
                    msj += "\n- No se pudo obtener *Recargaqui/BAIT (Recargas)* tras varios intentos."
                    if saldo_pagaqui is not None:
                        msj += f"\n- Pagaqui (Saldo Final): ${saldo_pagaqui:,.2f} (solo informativo)"
                enviar_whatsapp(msj)
                exit(1)
            else:
                print(f"Reintentando ciclo completo en 10 segundos... (Falla pagaqui={falla_pagaqui}, falla bait={falla_bait})\n")
                time.sleep(10)
