"""
Django settings for GestiStore project.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_local_env(path):
    """Carga .env para desarrollo sin depender de paquetes externos."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_local_env(BASE_DIR / '.env')

SECRET_KEY = 'django-insecure-3y(nhx64%j#$t9w)%$nk5gxrror12k%2kr!z2=m^kg2l*^nng3'

DEBUG = os.getenv('DJANGO_DEBUG', 'true').lower() == 'true'

# Hosts habilitados para desarrollo. Se puede sobrescribir con
# DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,otra-ip".
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        'DJANGO_ALLOWED_HOSTS',
        'localhost,127.0.0.1,testserver,192.168.137.3',
    ).split(',')
    if host.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip().rstrip('/')
    for origin in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

# El iniciador fácil recibe tráfico HTTPS desde un túnel que se conecta al
# servidor por loopback. Solo en ese modo confiamos en X-Forwarded-Proto.
if os.getenv('TRUST_PROXY_HEADERS', '').lower() == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if os.getenv('DJANGO_SECURE_COOKIES', '').lower() == 'true':
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Dirección pública temporal usada en enlaces enviados por email. Los
# iniciadores la configuran automáticamente.
# Si queda vacía, Django usa automáticamente el host de la solicitud actual.
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'Tienda',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Si un formulario de autenticación quedó abierto al reiniciar el enlace
# temporal, recuperamos la pantalla sin procesar el POST vencido.
CSRF_FAILURE_VIEW = 'Tienda.views.csrf_failure'

ROOT_URLCONF = 'GestiStore.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'Templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'GestiStore.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-ar'
TIME_ZONE = 'America/Argentina/Buenos_Aires'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'Tienda', 'static')]

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# Correo: las credenciales se leen desde variables de entorno o desde .env.
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.smtp.EmailBackend',
)
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'true').lower() == 'true'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv(
    'DEFAULT_FROM_EMAIL',
    f'AmpereStore <{EMAIL_HOST_USER}>' if EMAIL_HOST_USER else 'AmpereStore <noreply@localhost>',
)
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '15'))

# Segundo factor por email.
EMAIL_OTP_EXPIRY_SECONDS = 600
EMAIL_OTP_MAX_ATTEMPTS = 5
EMAIL_OTP_RESEND_SECONDS = 60

# Passkeys / WebAuthn. En producción conviene fijar estos valores al dominio HTTPS.
WEBAUTHN_RP_NAME = os.getenv('WEBAUTHN_RP_NAME', 'AmpereStore')
WEBAUTHN_RP_ID = os.getenv('WEBAUTHN_RP_ID', '').strip()
WEBAUTHN_ORIGIN = os.getenv('WEBAUTHN_ORIGIN', '').strip().rstrip('/')
WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS = 300

# Reconocimiento facial en navegador. La distancia es menor cuanto más se
# parecen dos descriptores. Se exige que cada captura quede por debajo del
# umbral, no solamente el promedio de las lecturas.
FACE_RECOGNITION_MODEL_VERSION = 'vladmandic-face-api-1.7.15-strict-v2'
FACE_RECOGNITION_THRESHOLD = float(os.getenv('FACE_RECOGNITION_THRESHOLD', '0.42'))
FACE_CAPTURE_CONSISTENCY_THRESHOLD = 0.35
FACE_LOGIN_MAX_ATTEMPTS = 5
FACE_LOGIN_ATTEMPT_WINDOW_SECONDS = 300

# Los enlaces de recuperación de contraseña vencen después de una hora.
PASSWORD_RESET_TIMEOUT = 3600

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
