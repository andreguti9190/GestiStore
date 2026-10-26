"""Prueba local del WebSocket autenticado del panel vendedor."""

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode


PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'GestiStore.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from Tienda.models import Venta  # noqa: E402
from websockets.sync.client import connect  # noqa: E402


def available_port():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]
    finally:
        listener.close()


def wait_until_ready(port, process):
    for _ in range(100):
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ''
            raise RuntimeError(f'Uvicorn terminó antes de iniciar.\n{output}')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError('Uvicorn no inició dentro del tiempo esperado.')


def csrf_token(port, session_cookie):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    connection.request('GET', '/ventas/?periodo=todo', headers={
        'Cookie': session_cookie,
    })
    response = connection.getresponse()
    response.read()
    if response.status != 200:
        raise RuntimeError(f'El dashboard respondió HTTP {response.status}.')

    cookies = SimpleCookie()
    for header, value in response.getheaders():
        if header.lower() == 'set-cookie':
            cookies.load(value)
    connection.close()
    token = cookies.get(settings.CSRF_COOKIE_NAME)
    if not token:
        raise RuntimeError('El dashboard no entregó la cookie CSRF.')
    return token.value


def trigger_sale_update(port, session_cookie, csrf, sale):
    body = urlencode({
        'venta_id': sale.pk,
        'estado_pago': sale.estado_pago,
        'estado_envio': sale.estado_envio,
    })
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    connection.request('POST', '/ventas/', body=body, headers={
        'Content-Type': 'application/x-www-form-urlencoded',
        'Content-Length': str(len(body.encode())),
        'Cookie': f'{session_cookie}; {settings.CSRF_COOKIE_NAME}={csrf}',
        'X-CSRFToken': csrf,
        'Referer': f'http://127.0.0.1:{port}/ventas/',
    })
    response = connection.getresponse()
    response.read()
    connection.close()
    if response.status != 302:
        raise RuntimeError(
            f'La actualización de prueba respondió HTTP {response.status}.'
        )


def main():
    admin = User.objects.get(username='admin')
    sale = Venta.objects.order_by('-pk').first()
    if not sale:
        raise RuntimeError('Se necesita al menos una venta para probar el evento.')

    test_client = Client()
    test_client.force_login(admin)
    session_key = test_client.cookies[settings.SESSION_COOKIE_NAME].value
    session_cookie = f'{settings.SESSION_COOKIE_NAME}={session_key}'
    port = available_port()
    process = subprocess.Popen(
        [
            sys.executable, '-m', 'uvicorn', 'GestiStore.asgi:application',
            '--host', '127.0.0.1', '--port', str(port), '--lifespan', 'off',
            '--log-level', 'warning',
        ],
        cwd=PROJECT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        wait_until_ready(port, process)
        csrf = csrf_token(port, session_cookie)
        with connect(
            f'ws://127.0.0.1:{port}/ws/ventas/',
            origin=f'http://127.0.0.1:{port}',
            additional_headers={'Cookie': session_cookie},
            open_timeout=5,
            close_timeout=2,
        ) as websocket:
            ready = json.loads(websocket.recv(timeout=5))
            if ready.get('type') != 'ready' or not ready.get('revision'):
                raise RuntimeError('El servidor no confirmó el canal del dashboard.')

            trigger_sale_update(port, session_cookie, csrf, sale)
            event = json.loads(websocket.recv(timeout=5))
            if event.get('type') != 'sale.updated' or event.get('saleId') != sale.pk:
                raise RuntimeError('El canal no entregó el evento de venta.')
            print('WebSocket autenticado y evento de venta entregado: OK')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        test_client.logout()


if __name__ == '__main__':
    main()
