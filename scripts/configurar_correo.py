"""Configura Gmail localmente y valida SMTP sin enviar correos de prueba."""

import getpass
import os
import smtplib
import ssl
import tempfile
from email.utils import parseaddr
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent


def save_mail_settings(path, address, password):
    updates = {
        'EMAIL_BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
        'EMAIL_HOST': 'smtp.gmail.com',
        'EMAIL_PORT': '587',
        'EMAIL_USE_TLS': 'true',
        'EMAIL_USE_SSL': 'false',
        'EMAIL_HOST_USER': address,
        'EMAIL_HOST_PASSWORD': password,
        'DEFAULT_FROM_EMAIL': f'AmpereStore <{address}>',
    }
    lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    result = []
    for line in lines:
        key = line.split('=', 1)[0].strip()
        if key not in updates:
            result.append(line)
    result.extend(f'{key}={value}' for key, value in updates.items())
    # Reemplazo atómico: un corte no deja el archivo de configuración incompleto.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=path.parent, prefix='.mail-config-', delete=False,
        ) as target:
            temporary = Path(target.name)
            target.write('\n'.join(result) + '\n')
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main():
    print('Configuración de Gmail para AmpereStore\n')
    print('Usá el correo remitente y una contraseña de aplicación de Google.')
    print('Podés crearla desde https://myaccount.google.com/apppasswords')
    print('La contraseña se ingresa aquí, oculta; no la pegues en el chat.\n')
    address = input('Correo remitente: ').strip()
    if parseaddr(address)[1] != address or '@' not in address or any(
        char.isspace() for char in address
    ):
        raise ValueError('Ingresá un correo válido.')
    password = ''.join(getpass.getpass('Contraseña de aplicación (oculta): ').split())
    if len(password) != 16 or not password.isascii() or not password.isalnum():
        raise ValueError('Ingresá la contraseña de aplicación de 16 caracteres que genera Google.')

    print('\nComprobando conexión y autenticación con Gmail…')
    with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as connection:
        connection.ehlo()
        connection.starttls(context=ssl.create_default_context())
        connection.ehlo()
        connection.login(address, password)

    save_mail_settings(PROJECT_DIR / '.env', address, password)
    print('Gmail aceptó las credenciales. Configuración guardada en .env.')
    print('Cerrá el iniciador actual y volvé a abrir iniciar_facil.bat.')
    print('No se envió ningún correo de prueba.')


if __name__ == '__main__':
    try:
        main()
    except smtplib.SMTPAuthenticationError:
        print('Gmail rechazó las credenciales. Revisá el correo y la contraseña de aplicación.')
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print('\nConfiguración cancelada.')
        raise SystemExit(1)
    except (OSError, smtplib.SMTPException, ValueError) as error:
        print(f'No se pudo configurar el correo ({type(error).__name__}). Revisá los datos y la conexión.')
        raise SystemExit(1)
