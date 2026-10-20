"""Inicia la aplicación ASGI con TLS para la demo en red local."""

import argparse
import asyncio
import sys
import threading
from pathlib import Path

import uvicorn

from servidor_certificado import create_certificate_server


def main():
    project_dir = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_dir))

    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--certificate', required=True)
    parser.add_argument('--key', required=True)
    parser.add_argument('--ca-certificate')
    parser.add_argument('--certificate-port', type=int)
    parser.add_argument('--https-url')
    args = parser.parse_args()

    certificate_server = None
    certificate_thread = None
    if args.certificate_port:
        if not args.ca_certificate or not args.https_url:
            raise SystemExit(
                'Con --certificate-port hacen falta --ca-certificate y --https-url.'
            )
        certificate_server = create_certificate_server(
            args.host,
            args.certificate_port,
            args.ca_certificate,
            args.https_url,
        )
        certificate_thread = threading.Thread(
            target=certificate_server.serve_forever,
            name='amperestore-certificate-server',
            daemon=True,
        )
        certificate_thread.start()
    elif args.ca_certificate or args.https_url:
        raise SystemExit('--certificate-port es obligatorio para instalar la CA.')

    config = uvicorn.Config(
        'GestiStore.asgi:application',
        host=args.host,
        port=args.port,
        ssl_certfile=args.certificate,
        ssl_keyfile=args.key,
        lifespan='off',
    )
    server = uvicorn.Server(config)

    # Uvicorn selecciona ProactorEventLoop en Windows. Algunas instalaciones
    # recientes de Python se bloquean al crear su socket interno; el selector
    # es compatible con este servidor y evita ese problema.
    try:
        if sys.platform == 'win32':
            asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
        else:
            server.run()
    finally:
        if certificate_server is not None:
            certificate_server.shutdown()
            certificate_server.server_close()
        if certificate_thread is not None:
            certificate_thread.join(timeout=2)


if __name__ == '__main__':
    main()
