import os
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

# Credenciales Twilio
TWILIO_SID = os.getenv('TWILIO_SID')
TWILIO_TOKEN = os.getenv('TWILIO_TOKEN')
TWILIO_WHATSAPP = 'whatsapp:+14155238886'
TO_WHATSAPP = 'whatsapp:+524492155882'  # Cambia a tus destinatarios

client = Client(TWILIO_SID, TWILIO_TOKEN)

# Credenciales Pagaqui
PAGAQUI_USER = os.getenv('PAGAQUI_USER')
PAGAQUI_PASS = os.getenv('PAGAQUI_PASS')

def notificar(saldo):
    msg = f'¡ALERTA! El saldo en Pagaqui es bajo: {saldo}'
    client.messages.create(
        body=msg,
        from_=TWILIO_WHATSAPP,
        to=TO_WHATSAPP
    )

def obtener_saldo_pagaqui():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')

    with webdriver.Chrome(options=chrome_options) as driver:
        driver.get('https://www.pagaqui.com.mx/homepagaqui.aspx')
        driver.find_element(By.NAME, 'username').send_keys(PAGAQUI_USER)
        driver.find_element(By.NAME, 'password').send_keys(PAGAQUI_PASS)
        driver.find_element(By.ID, 'entrar').click()
        time.sleep(2)

        # Si aparece el checkbox de forzar sesión
        try:
            checkbox = driver.find_element(By.ID, 'forcelogout')
            if checkbox.is_displayed():
                checkbox.click()
                driver.find_element(By.ID, 'entrar').click()
                time.sleep(2)
        except Exception:
            pass  # No apareció

        # Ir a "Administración" > "Info. Cuenta"
        driver.find_element(By.LINK_TEXT, 'Administración').click()
        driver.find_element(By.ID, 'ctl00_InfoCuentaLink').click()
        time.sleep(2)

        # Buscar el saldo de abonos
        filas = driver.find_elements(By.XPATH, "//div[contains(@class,'row')]")
        for fila in filas:
            if "Saldo Final" in fila.text:
                abonos = fila.find_elements(By.XPATH, ".//div[contains(@class,'col-md-3')]")[0].text
                return abonos.strip()

        return None

def parsear_saldo(s):
    # Convierte "$ 2,345.67" a float
    return float(s.replace('$', '').replace(',', '').strip())

def checar_y_notificar():
    saldo = obtener_saldo_pagaqui()
    if saldo:
        monto = parsear_saldo(saldo)
        print(f"Saldo actual: {monto}")
        if monto <= 3000:
            notificar(saldo)
    else:
        print("No se pudo obtener el saldo.")

if __name__ == '__main__':
    hora = datetime.now().hour
    if 7 <= hora <= 21:
        checar_y_notificar()
