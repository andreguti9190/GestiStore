"""Servidor HTTP mínimo para instalar la CA local antes de abrir AmpereStore."""

import argparse
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


CERTIFICATE_ROUTE = "/amperestore-ca.cer"


def _installation_page(https_url):
    safe_url = html.escape(https_url, quote=True)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Conectar a AmpereStore</title>
  <style>
    body {{ margin: 0; background: #eefaff; color: #27265f; font: 17px/1.5 system-ui, sans-serif; }}
    main {{ max-width: 720px; margin: 0 auto; padding: 32px 20px 56px; }}
    section {{ background: white; border: 1px solid #cbdfea; border-radius: 18px; padding: 24px; box-shadow: 0 12px 32px #31567a18; }}
    h1, h2 {{ line-height: 1.15; }}
    a.button {{ display: block; margin: 20px 0; padding: 15px; border-radius: 12px; background: #4b5fa4; color: white; text-align: center; font-weight: 700; text-decoration: none; }}
    code {{ overflow-wrap: anywhere; }}
    .warning {{ padding: 14px; border-radius: 10px; background: #fff5d8; color: #654b00; }}
  </style>
</head>
<body>
<main>
  <section>
    <h1>Conectar este dispositivo a AmpereStore</h1>
    <p>Este paso instala solamente el certificado público que permite confiar en el HTTPS local.</p>
    <a class="button" href="{CERTIFICATE_ROUTE}">1. Descargar certificado de AmpereStore</a>

    <h2>iPhone o iPad</h2>
    <ol>
      <li>Descargá el certificado y aceptá el perfil.</li>
      <li>Abrí <strong>Ajustes → Perfil descargado</strong> e instalalo.</li>
      <li>Abrí <strong>Ajustes → General → Información → Ajustes de confianza de certificados</strong> y activá la confianza total para AmpereStore.</li>
    </ol>

    <h2>Otra computadora con Windows</h2>
    <ol>
      <li>Abrí el archivo descargado y elegí <strong>Instalar certificado</strong>.</li>
      <li>Seleccioná <strong>Usuario actual</strong> y el almacén <strong>Entidades de certificación raíz de confianza</strong>.</li>
    </ol>

    <h2>Android</h2>
    <p>Instalalo desde los ajustes de seguridad como certificado de CA. El nombre exacto del menú cambia según el fabricante.</p>

    <p class="warning">Después de instalarlo, cerrá completamente el navegador y volvé a abrirlo.</p>
    <a class="button" href="{safe_url}">2. Abrir AmpereStore con HTTPS</a>
    <p>Dirección segura: <code>{safe_url}</code></p>
  </section>
</main>
</body>
</html>""".encode("utf-8")


def create_certificate_server(host, port, certificate_path, https_url):
    certificate_path = Path(certificate_path)
    page = _installation_page(https_url)

    class CertificateHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(page)
                return

            if self.path == CERTIFICATE_ROUTE and certificate_path.is_file():
                content = certificate_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-x509-ca-cert")
                self.send_header("Content-Disposition", 'attachment; filename="amperestore-ca.cer"')
                self.send_header("Content-Length", str(len(content)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(content)
                return

            self.send_error(404)

        def log_message(self, message, *args):
            print("Certificado: " + message % args)

    return ThreadingHTTPServer((host, port), CertificateHandler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--https-url", required=True)
    args = parser.parse_args()
    server = create_certificate_server(
        args.host,
        args.port,
        args.certificate,
        args.https_url,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
