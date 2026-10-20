"""Inicia AmpereStore con un enlace HTTPS público temporal y sin instalaciones."""

import argparse
import asyncio
import hashlib
import os
import platform
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_DIR / ".runtime"
TUNNEL_URL_PATTERN = re.compile(
    r"https://[a-z0-9-]+\.trycloudflare\.com",
    re.IGNORECASE,
)
CLOUDFLARED_VERSION = "2026.10.1"
CLOUDFLARED_SHA256_AMD64 = "4d2490e74082c5d48dbfedaf92576fa5bd1702379ab88eb7faa0cfbe8dc891b6"


def _available_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _tunnel_url(line):
    match = TUNNEL_URL_PATTERN.search(line)
    return match.group(0).rstrip("/") if match else None


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_cloudflared():
    installed = shutil.which("cloudflared")
    if installed:
        return installed

    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Esta PC no usa una arquitectura compatible con el iniciador fácil.")

    RUNTIME_DIR.mkdir(exist_ok=True)
    executable = RUNTIME_DIR / "cloudflared.exe"
    if executable.is_file() and _file_sha256(executable) == CLOUDFLARED_SHA256_AMD64:
        return str(executable)

    download = executable.with_suffix(".download")
    url = (
        "https://github.com/cloudflare/cloudflared/releases/download/"
        f"{CLOUDFLARED_VERSION}/cloudflared-windows-amd64.exe"
    )
    print("Preparando el acceso seguro por primera vez…")
    request = Request(url, headers={"User-Agent": "AmpereStore launcher"})
    try:
        with urlopen(request, timeout=60) as response, download.open("wb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
        if _file_sha256(download) != CLOUDFLARED_SHA256_AMD64:
            raise RuntimeError("La verificación de cloudflared no coincidió.")
        download.replace(executable)
    finally:
        if download.exists():
            download.unlink()
    return str(executable)


def _start_tunnel(local_port):
    cloudflared = _ensure_cloudflared()
    command = [
        cloudflared,
        "tunnel",
        "--url", f"http://127.0.0.1:{local_port}",
        "--no-autoupdate",
        "--protocol", "http2",
    ]
    process = subprocess.Popen(
        command,
        cwd=PROJECT_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    output = queue.Queue()
    waiting_for_url = threading.Event()

    def read_output():
        assert process.stdout is not None
        for line in process.stdout:
            if not waiting_for_url.is_set():
                output.put(line)
        output.put(None)

    threading.Thread(target=read_output, name="localhost-run-output", daemon=True).start()

    deadline = time.monotonic() + 45
    recent_output = []
    while time.monotonic() < deadline:
        if process.poll() is not None and output.empty():
            break
        try:
            line = output.get(timeout=0.5)
        except queue.Empty:
            continue
        if line is None:
            break
        recent_output.append(line.strip())
        recent_output = recent_output[-8:]
        public_url = _tunnel_url(line)
        if public_url:
            waiting_for_url.set()
            return process, public_url

    process.terminate()
    details = "\n".join(item for item in recent_output if item)
    raise RuntimeError(
        "No se pudo crear el enlace temporal en 45 segundos. "
        "Revisá la conexión a Internet.\n" + details
    )


def _copy_to_clipboard(value):
    if sys.platform != "win32" or not shutil.which("clip.exe"):
        return False
    result = subprocess.run(
        ["clip.exe"],
        input=value,
        text=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result.returncode == 0


def _configure_django(public_url):
    hostname = urlparse(public_url).hostname
    if not hostname:
        raise RuntimeError("El túnel devolvió una dirección inválida.")
    os.environ["DJANGO_ALLOWED_HOSTS"] = f"localhost,127.0.0.1,testserver,{hostname}"
    os.environ["DJANGO_CSRF_TRUSTED_ORIGINS"] = public_url
    os.environ["PUBLIC_BASE_URL"] = public_url
    os.environ["WEBAUTHN_RP_ID"] = hostname
    os.environ["WEBAUTHN_ORIGIN"] = public_url
    os.environ["TRUST_PROXY_HEADERS"] = "true"
    os.environ["DJANGO_DEBUG"] = "false"
    os.environ["DJANGO_SECURE_COOKIES"] = "true"
    os.environ["SERVE_STATIC_FILES"] = "true"
    os.environ["SERVE_MEDIA_FILES"] = "true"


def _stop_process(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-clipboard", action="store_true")
    parser.add_argument("--local-port", type=int)
    args = parser.parse_args()

    os.chdir(PROJECT_DIR)
    sys.path.insert(0, str(PROJECT_DIR))
    local_port = args.local_port or _available_local_port()

    print("\nIniciando AmpereStore…")
    print("Creando el acceso seguro para PC y celular…")
    tunnel, public_url = _start_tunnel(local_port)
    _configure_django(public_url)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'GestiStore.settings')
    from Tienda.emails import mail_configuration_problem
    email_problem = mail_configuration_problem()
    if email_problem:
        print(f'\nAVISO DE CORREO: {email_problem}')
        print('Abrí configurar_correo.bat y luego reiniciá AmpereStore.\n')

    print("\n" + "=" * 68)
    print("AMPERESTORE ESTÁ LISTO")
    print("=" * 68)
    print(f"\nEnlace para PC o celular:\n{public_url}\n")
    if not args.no_clipboard and _copy_to_clipboard(public_url):
        print("El enlace quedó copiado. Podés pegarlo y compartirlo.")
    print("Para usarlo en un celular, enviá o pegá allí este mismo enlace.")
    print("No hay que instalar certificados ni estar en el mismo Wi-Fi.")
    print("El enlace funciona mientras esta ventana permanezca abierta.")
    print("Para cerrar AmpereStore presioná Ctrl+C.\n")

    if not args.no_browser:
        timer = threading.Timer(1.5, webbrowser.open, args=(public_url,))
        timer.daemon = True
        timer.start()

    closing = threading.Event()
    try:
        import uvicorn

        config = uvicorn.Config(
            "GestiStore.asgi:application",
            host="127.0.0.1",
            port=local_port,
            lifespan="off",
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
            log_level="warning",
        )
        server = uvicorn.Server(config)

        def stop_if_tunnel_closes():
            tunnel.wait()
            if not closing.is_set() and not server.should_exit:
                print("\nEl enlace temporal se cerró. Volvé a iniciar AmpereStore.")
                server.should_exit = True

        threading.Thread(
            target=stop_if_tunnel_closes,
            name="localhost-run-monitor",
            daemon=True,
        ).start()

        if sys.platform == "win32":
            asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
        else:
            server.run()
    except KeyboardInterrupt:
        pass
    finally:
        closing.set()
        _stop_process(tunnel)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
