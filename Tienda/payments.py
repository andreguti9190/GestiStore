"""Integración server-to-server con Mercado Pago."""

import hashlib
import hmac
import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import PagoSandbox, Producto


logger = logging.getLogger(__name__)


class MercadoPagoError(Exception):
    """Error seguro para mostrar al usuario sin filtrar credenciales."""


def mercado_pago_configured():
    return bool(
        settings.MERCADOPAGO_ACCESS_TOKEN
        and settings.MERCADOPAGO_WEBHOOK_SECRET
    )


def _mercadopago_request(path, method='GET', payload=None, idempotency_key=''):
    if not settings.MERCADOPAGO_ACCESS_TOKEN:
        raise MercadoPagoError('Falta configurar el Access Token de Mercado Pago.')
    headers = {
        'Authorization': f'Bearer {settings.MERCADOPAGO_ACCESS_TOKEN}',
        'Accept': 'application/json',
        'User-Agent': 'AmpereStore/1.0',
    }
    body = None
    if payload is not None:
        body = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    if idempotency_key:
        headers['X-Idempotency-Key'] = idempotency_key
    request = Request(
        f'{settings.MERCADOPAGO_API_BASE_URL}{path}',
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            response_body = error.read().decode('utf-8', errors='replace')[:2000]
        except Exception:
            response_body = ''
        logger.warning(
            'Mercado Pago rechazo %s %s con HTTP %s. request_id=%s body=%s',
            method,
            path,
            error.code,
            error.headers.get('x-request-id', '') if error.headers else '',
            response_body,
        )
        raise MercadoPagoError(
            f'Mercado Pago rechazó la solicitud (código {error.code}).'
        ) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise MercadoPagoError(
            'No pudimos comunicarnos con Mercado Pago. Intentá nuevamente.'
        ) from error


def _mercadopago_public_base_url(request):
    base_url = settings.PUBLIC_BASE_URL or request.build_absolute_uri('/').rstrip('/')
    parsed = urlparse(base_url)
    if parsed.scheme != 'https' or parsed.hostname in {'localhost', '127.0.0.1'}:
        raise MercadoPagoError(
            'Mercado Pago necesita que abras la tienda desde el enlace HTTPS del túnel.'
        )
    return base_url.rstrip('/')


def create_mercadopago_preference(payment, request):
    """Crea una preferencia de Checkout Pro y guarda el enlace de redirección."""
    if not mercado_pago_configured():
        raise MercadoPagoError('La integración de Mercado Pago no está completa.')
    base_url = _mercadopago_public_base_url(request)
    return_url = f'{base_url}{reverse("mercadopago_retorno")}'
    notification_url = f'{base_url}{reverse("mercadopago_webhook")}'
    sale = payment.venta
    items = [{
        'id': str(detail.producto_id),
        'title': detail.producto.nombre[:120],
        'quantity': detail.cantidad,
        'currency_id': 'ARS',
        'unit_price': float(detail.precio_unitario),
    } for detail in sale.detalles.select_related('producto').all()]
    preference_data = {
        'items': items,
        'external_reference': sale.codigo,
        'back_urls': {
            'success': return_url,
            'pending': return_url,
            'failure': return_url,
        },
        'auto_return': 'approved',
        'notification_url': notification_url,
        'statement_descriptor': 'AMPERESTORE',
        'metadata': {'venta_id': sale.pk, 'venta_codigo': sale.codigo},
    }
    # En sandbox Mercado Pago debe tomar la identidad del comprador de prueba
    # autenticado en su propio checkout. Enviar aqui el correo real de la
    # cuenta local mezcla identidades de prueba y productivas y puede terminar
    # en la pantalla generica "algo anduvo mal" al procesar la tarjeta.
    # En produccion si lo enviamos para mejorar el reconocimiento del pagador.
    if sale.usuario.email and settings.MERCADOPAGO_MODE != 'test':
        preference_data['payer'] = {'email': sale.usuario.email}
    response = _mercadopago_request(
        '/checkout/preferences',
        method='POST',
        payload=preference_data,
        idempotency_key=f'ampere-preference-{payment.referencia}',
    )
    checkout_url = (
        response.get('sandbox_init_point')
        if settings.MERCADOPAGO_MODE == 'test'
        else response.get('init_point')
    ) or response.get('init_point')
    if not response.get('id') or not checkout_url:
        raise MercadoPagoError('Mercado Pago no devolvió un enlace de pago válido.')
    payment.preferencia_externa = str(response['id'])[:120]
    payment.checkout_url = str(checkout_url)[:500]
    payment.save(update_fields=[
        'preferencia_externa', 'checkout_url', 'actualizado_en',
    ])
    return payment.checkout_url


def fetch_mercadopago_payment(payment_id):
    return _mercadopago_request(f'/v1/payments/{quote(str(payment_id), safe="")}')


def refund_mercadopago_payment(payment):
    if not payment.pago_externo_id:
        raise MercadoPagoError('El pago todavía no tiene una operación acreditada para reembolsar.')
    return _mercadopago_request(
        f'/v1/payments/{quote(payment.pago_externo_id, safe="")}/refunds',
        method='POST',
        payload={},
        idempotency_key=f'ampere-refund-{payment.referencia}',
    )


def validate_mercadopago_signature(signature, request_id, data_id, now=None):
    """Valida la firma HMAC documentada por Mercado Pago."""
    if not settings.MERCADOPAGO_WEBHOOK_SECRET:
        return False
    parts = {}
    for part in (signature or '').split(','):
        key, separator, value = part.strip().partition('=')
        if separator:
            parts[key] = value
    timestamp = parts.get('ts', '')
    received_hash = parts.get('v1', '')
    if not all((timestamp, received_hash, request_id, data_id)):
        return False
    try:
        timestamp_number = float(timestamp)
    except ValueError:
        return False
    timestamp_seconds = timestamp_number / 1000 if timestamp_number > 10_000_000_000 else timestamp_number
    if abs((now if now is not None else time.time()) - timestamp_seconds) > 600:
        return False
    manifest = f'id:{data_id};request-id:{request_id};ts:{timestamp};'
    expected = hmac.new(
        settings.MERCADOPAGO_WEBHOOK_SECRET.encode('utf-8'),
        manifest.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received_hash)


def _release_reserved_stock(payment):
    if payment.stock_liberado:
        return
    for detail in payment.venta.detalles.select_related('producto').all():
        product = Producto.objects.select_for_update().get(pk=detail.producto_id)
        product.stock += detail.cantidad
        product.save(update_fields=['stock'])
    payment.stock_liberado = True


def cancel_reserved_payment(payment, reason):
    """Cancela un intento fallido y devuelve el stock una sola vez."""
    with transaction.atomic():
        locked = (
            PagoSandbox.objects.select_for_update()
            .select_related('venta')
            .get(pk=payment.pk)
        )
        if locked.estado in {'aprobado', 'reembolsado'}:
            return locked
        locked.estado = 'rechazado'
        locked.motivo = str(reason)[:120]
        _release_reserved_stock(locked)
        sale = locked.venta
        sale.estado_pago = 'rechazado'
        sale.estado = 'cancelada'
        sale.estado_envio = 'cancelado'
        sale.save(update_fields=['estado_pago', 'estado', 'estado_envio'])
        locked.save(update_fields=[
            'estado', 'motivo', 'stock_liberado', 'actualizado_en',
        ])
        from .realtime import publish_dashboard_event
        transaction.on_commit(
            lambda: publish_dashboard_event('sale.updated', sale.pk)
        )
        return locked


def apply_mercadopago_status(payment, payload):
    """Sincroniza una respuesta verificada de la API de Mercado Pago."""
    external_reference = str(payload.get('external_reference') or '')
    external_payment_id = str(payload.get('id') or '')
    if not external_reference or external_reference != payment.venta.codigo:
        raise MercadoPagoError('La referencia del pago no coincide con el pedido.')
    if not external_payment_id:
        raise MercadoPagoError('Mercado Pago no devolvió el identificador del pago.')

    with transaction.atomic():
        locked = (
            PagoSandbox.objects.select_for_update()
            .select_related('venta')
            .get(pk=payment.pk, proveedor='mercadopago')
        )
        if locked.pago_externo_id and locked.pago_externo_id != external_payment_id:
            raise MercadoPagoError('El identificador del pago no coincide con el pedido.')

        status = str(payload.get('status') or '').lower()
        old_status = locked.estado
        terminal = old_status in {'aprobado', 'rechazado', 'reembolsado'}
        if terminal and status in {'pending', 'in_process', 'authorized'}:
            return locked, False
        if old_status == 'reembolsado' and status != 'refunded':
            return locked, False

        sale = locked.venta
        if status == 'approved':
            if locked.stock_liberado:
                raise MercadoPagoError('El stock de este pedido ya fue liberado.')
            locked.estado = 'aprobado'
            locked.aprobado_en = locked.aprobado_en or timezone.now()
            sale.estado_pago = 'pagado'
            sale.estado = 'completada'
            sale.estado_envio = 'preparando'
        elif status in {'rejected', 'cancelled', 'expired'}:
            locked.estado = 'rechazado'
            _release_reserved_stock(locked)
            sale.estado_pago = 'rechazado'
            sale.estado = 'cancelada'
            sale.estado_envio = 'cancelado'
        elif status in {'refunded', 'charged_back'}:
            locked.estado = 'reembolsado'
            _release_reserved_stock(locked)
            sale.estado_pago = 'reembolsado'
            sale.estado = 'cancelada'
            sale.estado_envio = 'cancelado'
        else:
            locked.estado = 'procesando' if status in {'pending', 'in_process', 'authorized'} else 'pendiente'
            sale.estado_pago = 'procesando' if locked.estado == 'procesando' else 'pendiente'
            sale.estado = 'pendiente'
            sale.estado_envio = 'pendiente'

        card = payload.get('card') or {}
        payment_method = payload.get('payment_method') or {}
        locked.pago_externo_id = external_payment_id[:120]
        locked.marca_tarjeta = str(
            payment_method.get('id') or payload.get('payment_method_id') or ''
        )[:20].replace('_', ' ').title()
        locked.ultimos_cuatro = str(card.get('last_four_digits') or '')[-4:]
        locked.motivo = str(payload.get('status_detail') or '')[:120]
        sale.save(update_fields=['estado_pago', 'estado', 'estado_envio'])
        locked.save(update_fields=[
            'pago_externo_id', 'marca_tarjeta', 'ultimos_cuatro', 'estado',
            'motivo', 'stock_liberado', 'aprobado_en', 'actualizado_en',
        ])
        changed = old_status != locked.estado
        from .realtime import publish_dashboard_event
        transaction.on_commit(
            lambda: publish_dashboard_event('sale.updated', sale.pk)
        )
        return locked, changed


def sync_payment_from_admin(sale, payment_status):
    """Mantiene el registro de sandbox alineado con cambios del vendedor."""
    payment = (
        PagoSandbox.objects.select_for_update()
        .filter(venta=sale)
        .first()
    )
    if not payment:
        return None

    if payment_status == 'pagado':
        if payment.stock_liberado:
            raise ValueError(
                'El stock de este pedido ya fue liberado; generá una nueva compra.'
            )
        payment.estado = 'aprobado'
        payment.motivo = ''
        payment.aprobado_en = payment.aprobado_en or timezone.now()
    elif payment_status == 'rechazado':
        payment.estado = 'rechazado'
        payment.motivo = 'Pago rechazado manualmente por el vendedor.'
        _release_reserved_stock(payment)
    elif payment_status == 'reembolsado':
        payment.estado = 'reembolsado'
        payment.motivo = 'Pago marcado como reembolsado por el vendedor.'
        _release_reserved_stock(payment)
    elif payment_status == 'procesando':
        payment.estado = 'procesando'
    else:
        payment.estado = 'pendiente'

    payment.save(update_fields=[
        'estado', 'motivo', 'stock_liberado', 'aprobado_en', 'actualizado_en',
    ])
    return payment
