"""
ASGI config for GestiStore project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import os

from django.conf import settings
from django.core.asgi import get_asgi_application
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'GestiStore.settings')

application = get_asgi_application()

# Uvicorn no incluye el servidor de archivos estáticos de ``runserver``.
# Lo agregamos solamente para esta demo cuando DEBUG está habilitado.
if settings.DEBUG or os.getenv('SERVE_STATIC_FILES', '').lower() == 'true':
    application = ASGIStaticFilesHandler(application)
