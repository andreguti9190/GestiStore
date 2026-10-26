"""Canal WebSocket liviano para actualizar el panel vendedor en tiempo real."""

import asyncio
import json
import threading
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.core import signing
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count, Max
from django.utils.crypto import constant_time_compare


class DashboardEventBroker:
    """Distribuye eventos desde vistas síncronas a conexiones ASGI."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = {}

    async def subscribe(self):
        token = object()
        queue = asyncio.Queue(maxsize=20)
        with self._lock:
            self._subscribers[token] = (asyncio.get_running_loop(), queue)
        return token, queue

    async def unsubscribe(self, token):
        with self._lock:
            self._subscribers.pop(token, None)

    @staticmethod
    def _enqueue(queue, payload):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(payload)

    def publish(self, payload):
        with self._lock:
            subscribers = list(self._subscribers.items())
        stale = []
        for token, (loop, queue) in subscribers:
            try:
                loop.call_soon_threadsafe(self._enqueue, queue, payload)
            except RuntimeError:
                stale.append(token)
        if stale:
            with self._lock:
                for token in stale:
                    self._subscribers.pop(token, None)


dashboard_events = DashboardEventBroker()


def get_dashboard_revision():
    from .models import Venta

    state = Venta.objects.aggregate(total=Count('pk'), latest=Max('pk'))
    return f"{state['total']}:{state['latest'] or 0}"


def publish_dashboard_event(event_type, sale_id):
    dashboard_events.publish({
        'type': event_type,
        'saleId': sale_id,
        'revision': get_dashboard_revision(),
    })


def _header(scope, name):
    expected = name.lower().encode('ascii')
    for key, value in scope.get('headers', []):
        if key.lower() == expected:
            return value.decode('latin1')
    return ''


def _same_origin(scope):
    host = _header(scope, 'host').split(':', 1)[0].strip('[]').lower()
    origin = _header(scope, 'origin')
    try:
        return bool(host and urlsplit(origin).hostname.lower() == host)
    except (AttributeError, ValueError):
        return False


def _session_key(scope):
    cookie = SimpleCookie()
    try:
        cookie.load(_header(scope, 'cookie'))
    except (signing.BadSignature, CookieError):
        return ''
    morsel = cookie.get(settings.SESSION_COOKIE_NAME)
    return morsel.value if morsel else ''


def _authenticated_admin(session_key):
    if not session_key:
        return None
    data = SessionStore(session_key=session_key).load()
    user_id = data.get(SESSION_KEY)
    backend = data.get(BACKEND_SESSION_KEY)
    if not user_id or backend not in settings.AUTHENTICATION_BACKENDS:
        return None
    user = User.objects.select_related('perfil').filter(pk=user_id, is_active=True).first()
    if not user:
        return None
    session_hash = data.get(HASH_SESSION_KEY, '')
    if not session_hash or not constant_time_compare(session_hash, user.get_session_auth_hash()):
        return None
    try:
        return user.pk if user.perfil.rol == 'admin' else None
    except ObjectDoesNotExist:
        return None


async def dashboard_websocket(scope, receive, send):
    """WebSocket autenticado y limitado al mismo origen del panel."""
    opening = await receive()
    if opening.get('type') != 'websocket.connect':
        return
    if not _same_origin(scope):
        await send({'type': 'websocket.close', 'code': 4403})
        return

    session_key = _session_key(scope)
    if not session_key:
        await send({'type': 'websocket.close', 'code': 4403})
        return
    user_id = await sync_to_async(_authenticated_admin, thread_sensitive=False)(session_key)
    if not user_id:
        await send({'type': 'websocket.close', 'code': 4403})
        return

    await send({'type': 'websocket.accept'})
    token, event_queue = await dashboard_events.subscribe()
    receive_task = asyncio.create_task(receive())
    event_task = asyncio.create_task(event_queue.get())
    try:
        revision = await sync_to_async(get_dashboard_revision, thread_sensitive=False)()
        await send({
            'type': 'websocket.send',
            'text': json.dumps({'type': 'ready', 'revision': revision}),
        })
        while True:
            done, _pending = await asyncio.wait(
                (receive_task, event_task),
                timeout=25,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                await send({
                    'type': 'websocket.send',
                    'text': json.dumps({'type': 'ping'}),
                })
                continue

            if receive_task in done:
                message = receive_task.result()
                if message.get('type') == 'websocket.disconnect':
                    break
                if message.get('text') == 'ping':
                    await send({
                        'type': 'websocket.send',
                        'text': json.dumps({'type': 'pong'}),
                    })
                receive_task = asyncio.create_task(receive())

            if event_task in done:
                payload = event_task.result()
                await send({
                    'type': 'websocket.send',
                    'text': json.dumps(payload),
                })
                event_task = asyncio.create_task(event_queue.get())
    finally:
        receive_task.cancel()
        event_task.cancel()
        await dashboard_events.unsubscribe(token)
