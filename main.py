# -*- coding: utf-8 -*-
import os
import re
import time
import unicodedata
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
    Devuelve (target_context, locator, selector_usado) para el primer selector encontrado (state='attached')
    en la página o en cualquier frame. Lanza PlaywrightTimeout si no aparece a tiempo.
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
        found = _try_in_target(page)
        if found:
            return found
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

def _norm_laxo(s: str) -> str:
    return " ".join(_norm(s).split())

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
    [page] + page.frames (frames ya poblados).
    """
    page.goto("https://recargaquiws.com.mx/login.aspx", wait_until="domcontentloaded")
    tgt_user, user_loc, _ = _find_in_page_or_frames(page, USERNAME_SELECTORS, timeout=15000)
    _, pass_loc, _ = _find_in_page_or_frames(page, PASSWORD_SELECTORS, timeout=15000)

    _safe_type(user_loc, RECARGAQUI_USER)
    _safe_type(pass_loc, RECARGAQUI_PASS)

    for sel in ["#forcelogout", "input[name='forcelogout']"]:
        try:
            fl = tgt_user.locator(sel)
            if fl.count() > 0:
                fl.check()
                break
        except Exception:
            pass

    btn = _first_present_locator(tgt_user, ["input#entrar", "button:has-text('Entrar')", "input[type='submit']"])
    if not btn:
        btn = _first_present_locator(page, ["input#entrar", "button:has-text('Entrar')", "input[type='submit']"])
    if not btn:
        raise RuntimeError("No se encontró el botón de 'Entrar' en Recargaqui.")
    btn.click()

    try:
        page.wait_for_url(_re_mod.compile(r"/home\.aspx$", _re_mod.I), timeout=15000)
    except PlaywrightTimeout:
        try:
            page.goto("https://recargaquiws.com.mx/home.aspx", wait_until="domcontentloaded")
        except Exception:
            pass

    try:
        mi = page.locator("#ctl00_mInicio, a[href='home.aspx']")
        if mi.count() > 0:
            mi.first.click()
            page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass

    return [page] + list(page.frames)

# ======== SOLO CAMBIÓ LA LÓGICA DEL DBGRID A PARTIR DE AQUÍ ========

def _poll_row9_lastcell_in_target(target, timeout_ms=20000, interval_ms=300):
    """
    NUEVO: Lee tablas priorizando .mGrid y devuelve el texto en la columna 'Saldo Actual'
    de la fila cuyo primer TD sea exactamente 'BAIT'.
    Si no existe encabezado claro, toma la última celda NUMÉRICA de la fila BAIT.
    """
    deadline = time.time() + timeout_ms / 1000.0
    last_err = None
    while time.time() < deadline:
        try:
            data = target.evaluate(
                """() => {
                    const grab = el => (el?.innerText ?? "").trim();
                    const pick = sel => Array.from(document.querySelectorAll(sel));
                    // Preferir .mGrid; si no hay, tomar todas
                    let tbls = pick("table.mGrid");
                    if (tbls.length === 0) tbls = pick("table");
                    return tbls.map(tbl => {
                        // headers
                        let headers = [];
                        const thead = tbl.querySelector("thead tr");
                        if (thead) {
                            headers = Array.from(thead.querySelectorAll("th,td")).map(grab);
                        } else {
                            const firstRow = tbl.querySelector("tr");
                            if (firstRow) headers = Array.from(firstRow.querySelectorAll("th,td")).map(grab);
                        }
                        // body rows
                        let bodyRows = Array.from(tbl.querySelectorAll("tbody tr"));
                        if (bodyRows.length === 0) {
                            const trs = Array.from(tbl.querySelectorAll("tr"));
                            bodyRows = trs.filter(tr => tr.querySelectorAll("td").length > 0);
                            const usedFirstAsHeader = !thead && !!tbl.querySelector("tr th");
                            if (usedFirstAsHeader && bodyRows.length > 0) bodyRows = bodyRows.slice(1);
                        }
                        const rows = bodyRows.map(tr =>
                            Array.from(tr.querySelectorAll("td")).map(grab)
                        );
                        return {headers, rows, isMGrid: tbl.classList.contains("mGrid")};
                    });
                }"""
            )
            # priorizar .mGrid
            data.sort((lambda a, b: (0 if a.get("isMGrid") else 1) - (0 if b.get("isMGrid") else 1)))

            for tbl in data:
                headers = tbl.get("headers") or []
                rows = tbl.get("rows") or []
                if not rows:
                    continue

                # Normaliza headers y busca 'Saldo Actual'
                headers_norm = [_norm_laxo(h) for h in headers]
                col_idx = None
                for i, h in enumerate(headers_norm):
                    if "saldo" in h and "actual" in h:
                        col_idx = i
                        break

                # Buscar fila BAIT (primera celda)
                fila_bait = None
                for r in rows:
                    if r and _norm_laxo(r[0]) == "bait":
                        fila_bait = r
                        break
                if fila_bait is None:
                    # fallback: en cualquier celda
                    for r in rows:
                        if any(_norm_laxo(c) == "bait" for c in r):
                            fila_bait = r
                            break
                if fila_bait is None:
                    continue

                // valor candidato
                let candidato = null;
                if (col_idx !== null && col_idx < fila_bait.length) {
                    candidato = fila_bait[col_idx];
                } else {
                    // última celda numérica
                    for (let i = fila_bait.length - 1; i >= 0; i--) {
                        const t = (fila_bait[i] || "").replace(/[\u00a0$,\s]/g, "");
                        if (t && !isNaN(Number(t))) { candidato = fila_bait[i]; break; }
                    }
                    if (!candidato && fila_bait.length > 0) candidato = fila_bait[fila_bait.length - 1];
                }
                if (candidato) return {text: candidato};
            }
        } catch (e) {
            last_err = e
        }
        time.sleep(interval_ms / 1000.0)
    if last_err:
        print(f"[poll grid] último error silencioso: {last_err}")
    return None

def _extract_row9_lastcell_from_html(html: str):
    """
    NUEVO Fallback HTML:
      - Encuentra la primera tabla .mGrid (o la primera <table>).
      - Detecta encabezados y la columna 'Saldo Actual'.
      - Busca la fila cuyo primer <td> sea 'BAIT' y devuelve su 'Saldo Actual'
        (o la última celda numérica si no hay encabezado).
    """
    try:
        # tomar la tabla .mGrid primero
        m = re.search(r"<table[^>]*class=[\"'][^\"']*mGrid[^\"']*[\"'][^>]*>(.*?)</table>", html, re.S | re.I)
        if not m:
            m = re.search(r"<table[^>]*>(.*?)</table>", html, re.S | re.I)
        if not m:
            return None
        table_html = m.group(0)

        # headers
        thead = re.search(r"<thead[^>]*>(.*?)</thead>", table_html, re.S | re.I)
        if thead:
            header_row = re.search(r"<tr[^>]*>(.*?)</tr>", thead.group(1), re.S | re.I)
            headers_html = header_row.group(1) if header_row else ""
        else:
            first_tr = re.search(r"<tr[^>]*>(.*?)</tr>", table_html, re.S | re.I)
            headers_html = first_tr.group(1) if first_tr else ""

        headers = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", headers_html, re.S | re.I)]
        headers_norm = [_norm_laxo(h) for h in headers]
        col_idx = None
        for i, h in enumerate(headers_norm):
            if "saldo" in h and "actual" in h:
                col_idx = i
                break

        # body rows
        tbody = re.search(r"<tbody[^>]*>(.*?)</tbody>", table_html, re.S | re.I)
        rows_html = tbody.group(1) if tbody else table_html
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", rows_html, re.S | re.I)

        def _cells(row_html):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S | re.I)
            return [re.sub(r"<[^>]+>", "", td).strip() for td in tds]

        for row_html in rows:
            cells = _cells(row_html)
            if not cells:
                continue
            if _norm_laxo(cells[0]) == "bait" or any(_norm_laxo(c) == "bait" for c in cells):
                if col_idx is not None and col_idx < len(cells):
                    return cells[col_idx]
                # última celda numérica
                for i in range(len(cells)-1, -1, -1):
                    if _to_float(cells[i]) is not None:
                        return cells[i]
                return cells[-1]
        return None
    except Exception as e:
        print(f"Regex fallback error: {e}")
        return None

def _extraer_bait_saldo_actual_en_target(target):
    """
    Devuelve el 'Saldo Actual' de BAIT usando:
      - Primero DOM (.mGrid + encabezado 'Saldo Actual' + fila 'BAIT')
      - Luego fallback HTML con la misma lógica.
      - Devuelve float o None
    """
    # 1) DOM
    res = _poll_row9_lastcell_in_target(target, timeout_ms=20000, interval_ms=300)
    if res and isinstance(res, dict):
        val = _to_float(res.get("text"))
        if val is not None:
            print(f"BAIT / Saldo Actual (DOM en frame): {val}")
            return val

    # 2) HTML
    try:
        html = target.content()
    except Exception:
        html = ""
    if html:
        last_text = _extract_row9_lastcell_from_html(html)
        if last_text:
            val = _to_float(last_text)
            if val is not None:
                print(f"BAIT / Saldo Actual (HTML en frame): {val}")
                return val

    return None

# ======== FIN DE LA SECCIÓN CAMBIADA DEL DBGRID ========

def obtener_saldo_recargaqui():
    """
    Devuelve el 'Saldo Actual' de la FILA 9 (BAIT) en Recargaqui.
    Recorre documento top y TODOS los frames, y toma SIEMPRE el último valor de esa fila.
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

                    saldo_bait_actual = None
                    for t in targets:
                        saldo_bait_actual = _extraer_bait_saldo_actual_en_target(t)
                        if saldo_bait_actual is not None:
                            break

                    if saldo_bait_actual is None:
                        print("No se encontró la fila 'BAIT' (fila 9) ni se pudo leer su 'Saldo Actual' (última columna) en ninguno de los frames.")

                    return saldo_bait_actual

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
    saldo_bait_actual = obtener_saldo_recargaqui()  # <-- Saldo Actual de BAIT (última columna fila 9)
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
            print(f"BAIT / Saldo Actual (fila 9, última columna): {saldo_bait}")

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
