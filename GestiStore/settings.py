"""
Django settings for GestiStore project.
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

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


configured_env_file = os.getenv('GESTISTORE_ENV_FILE', '').strip()
if configured_env_file:
    configured_env_path = Path(configured_env_file)
    if not configured_env_path.is_absolute():
        configured_env_path = BASE_DIR / configured_env_path
    _load_local_env(configured_env_path)
else:
    _load_local_env(BASE_DIR / '.env')

IS_VERCEL = os.getenv('VERCEL', '').lower() == '1'
LOCAL_SECRET_KEY = 'django-insecure-3y(nhx64%j#$t9w)%$nk5gxrror12k%2kr!z2=m^kg2l*^nng3'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', LOCAL_SECRET_KEY)
if IS_VERCEL and SECRET_KEY == LOCAL_SECRET_KEY:
    raise ImproperlyConfigured('Configurá DJANGO_SECRET_KEY en Vercel antes de desplegar.')

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
for vercel_host in (
    os.getenv('VERCEL_URL', ''),
    os.getenv('VERCEL_PROJECT_PRODUCTION_URL', ''),
):
    if vercel_host and vercel_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(vercel_host)

CSRF_TRUSTED_ORIGINS = [
    origin.strip().rstrip('/')
    for origin in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]
for vercel_host in (
    os.getenv('VERCEL_URL', ''),
    os.getenv('VERCEL_PROJECT_PRODUCTION_URL', ''),
):
    vercel_origin = f'https://{vercel_host}' if vercel_host else ''
    if vercel_origin and vercel_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(vercel_origin)

# El iniciador fácil recibe tráfico HTTPS desde un túnel que se conecta al
# servidor por loopback. Solo en ese modo confiamos en X-Forwarded-Proto.
if IS_VERCEL or os.getenv('TRUST_PROXY_HEADERS', '').lower() == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

if os.getenv('DJANGO_SECURE_COOKIES', '').lower() == 'true':
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Dirección pública temporal usada en enlaces enviados por email. Los
# iniciadores la configuran automáticamente.
# Si queda vacía, Django usa automáticamente el host de la solicitud actual.
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
if not PUBLIC_BASE_URL:
    vercel_public_host = (
        os.getenv('VERCEL_PROJECT_PRODUCTION_URL', '')
        or os.getenv('VERCEL_URL', '')
    )
    if vercel_public_host:
        PUBLIC_BASE_URL = f'https://{vercel_public_host}'

# Mercado Pago Checkout Pro. La clave privada se usa exclusivamente desde el
# servidor; nunca se envía al navegador ni se guarda en la base de datos.
MERCADOPAGO_ACCESS_TOKEN = os.getenv('MERCADOPAGO_ACCESS_TOKEN', '').strip()
MERCADOPAGO_PUBLIC_KEY = os.getenv('MERCADOPAGO_PUBLIC_KEY', '').strip()
MERCADOPAGO_WEBHOOK_SECRET = os.getenv('MERCADOPAGO_WEBHOOK_SECRET', '').strip()
MERCADOPAGO_MODE = os.getenv('MERCADOPAGO_MODE', 'test').strip().lower()
MERCADOPAGO_API_BASE_URL = os.getenv(
    'MERCADOPAGO_API_BASE_URL',
    'https://api.mercadopago.com',
).rstrip('/')

# Catálogo territorial oficial de Argentina. Se mantiene configurable para
# poder cambiar de instancia sin modificar el código de la tienda.
GEOREF_API_BASE_URL = os.getenv(
    'GEOREF_API_BASE_URL',
    'https://apis.datos.gob.ar/georef/api/v2.0',
).rstrip('/')

# Respaldo para direcciones que Georef reconoce pero devuelve sin coordenadas
# o con varias localidades posibles. No requiere una clave para esta demo.
ESRI_GEOCODE_URL = os.getenv(
    'ESRI_GEOCODE_URL',
    'https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates',
).strip()

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
ASGI_APPLICATION = 'GestiStore.asgi.application'

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
if IS_VERCEL and not DATABASE_URL:
    raise ImproperlyConfigured(
        'Configurá DATABASE_URL en Vercel (por ejemplo, conectando Neon).'
    )
if DATABASE_URL:
    parsed_database = urlparse(DATABASE_URL)
    if parsed_database.scheme not in {'postgres', 'postgresql'}:
        raise ImproperlyConfigured('DATABASE_URL debe ser una URL de PostgreSQL.')
    database_options = {
        key: values[-1]
        for key, values in parse_qs(parsed_database.query).items()
        if values
    }
    if IS_VERCEL:
        database_options.setdefault('sslmode', 'require')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': unquote(parsed_database.path.lstrip('/')),
            'USER': unquote(parsed_database.username or ''),
            'PASSWORD': unquote(parsed_database.password or ''),
            'HOST': parsed_database.hostname,
            'PORT': parsed_database.port or 5432,
            'OPTIONS': database_options,
            # Las Functions escalan horizontalmente; no conservamos conexiones
            # entre invocaciones y dejamos el pooling al proveedor serverless.
            'CONN_MAX_AGE': 0,
        }
    }
else:
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
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
SERVE_MEDIA_FILES = os.getenv('SERVE_MEDIA_FILES', '').lower() == 'true'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}
if os.getenv('BLOB_STORE_ID') or os.getenv('BLOB_READ_WRITE_TOKEN'):
    STORAGES['default'] = {
        'BACKEND': 'Tienda.storage.VercelBlobStorage',
    }
elif IS_VERCEL:
    raise ImproperlyConfigured(
        'Conectá un Vercel Blob público para conservar las imágenes de productos.'
    )

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
EMAIL_NOTICES_BACKGROUND = os.getenv(
    'EMAIL_NOTICES_BACKGROUND', 'false' if IS_VERCEL else 'true'
).lower() == 'true'

# Asistente con OpenAI. La clave se mantiene exclusivamente en el servidor.
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '').strip()
OPENAI_CHAT_MODEL = os.getenv('OPENAI_CHAT_MODEL', 'gpt-6-luna').strip()
OPENAI_RESPONSES_URL = os.getenv(
    'OPENAI_RESPONSES_URL', 'https://api.openai.com/v1/responses'
).strip()
OPENAI_TIMEOUT = int(os.getenv('OPENAI_TIMEOUT', '25'))
OPENAI_ASSISTANT_RATE_LIMIT = int(os.getenv('OPENAI_ASSISTANT_RATE_LIMIT', '12'))
OPENAI_ASSISTANT_RATE_WINDOW = int(os.getenv('OPENAI_ASSISTANT_RATE_WINDOW', '300'))
OPENAI_INCLUDE_STORE_CONTEXT = os.getenv(
    'OPENAI_INCLUDE_STORE_CONTEXT', 'false'
).lower() == 'true'

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
PURCHASE_FACE_AUTH_SECONDS = 180
IP_GEOLOCATION_URL_TEMPLATE = os.getenv(
    'IP_GEOLOCATION_URL_TEMPLATE', 'https://ipapi.co/{ip}/json/'
)

# Los enlaces de recuperación de contraseña vencen después de una hora.
PASSWORD_RESET_TIMEOUT = 3600

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_COOKIE_SAMESITE = 'Lax'
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    if IS_VERCEL:
        SECURE_SSL_REDIRECT = os.getenv('DJANGO_SECURE_SSL_REDIRECT', 'true').lower() == 'true'
        SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_SECURE_HSTS_SECONDS', '3600'))
        SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv(
            'DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', 'false'
        ).lower() == 'true'

# El inicio fácil guarda las excepciones reales aunque DEBUG esté desactivado,
# para que un error 500 no quede reducido a una pantalla sin información.
AMPERESTORE_ERROR_LOG = os.getenv('AMPERESTORE_ERROR_LOG', '').strip()
if AMPERESTORE_ERROR_LOG:
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'amperestore_error_file': {
                'class': 'logging.FileHandler',
                'filename': AMPERESTORE_ERROR_LOG,
                'encoding': 'utf-8',
                'level': 'ERROR',
            },
        },
        'loggers': {
            'django.request': {
                'handlers': ['amperestore_error_file'],
                'level': 'ERROR',
                'propagate': True,
            },
        },
    }
