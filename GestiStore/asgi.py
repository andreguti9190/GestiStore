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
from django.views.static import serve as serve_media

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'GestiStore.settings')

django_application = get_asgi_application()


class ASGIMediaFilesHandler(ASGIStaticFilesHandler):
    """Sirve MEDIA_ROOT en la demo sin mezclar iteradores síncronos y ASGI."""

    def get_base_url(self):
        return settings.MEDIA_URL

    def serve(self, request):
        return serve_media(
            request,
            self.file_path(request.path),
            document_root=settings.MEDIA_ROOT,
            show_indexes=False,
        )

# Uvicorn no incluye el servidor de archivos estáticos de ``runserver``.
# Lo agregamos solamente para esta demo cuando DEBUG está habilitado.
if settings.DEBUG or os.getenv('SERVE_STATIC_FILES', '').lower() == 'true':
    django_application = ASGIStaticFilesHandler(django_application)

if settings.SERVE_MEDIA_FILES:
    django_application = ASGIMediaFilesHandler(django_application)


from Tienda.realtime import dashboard_websocket  # noqa: E402


async def application(scope, receive, send):
    if scope['type'] == 'websocket':
        if scope.get('path') == '/ws/ventas/':
            await dashboard_websocket(scope, receive, send)
        else:
            await send({'type': 'websocket.close', 'code': 4404})
        return
    await django_application(scope, receive, send)
