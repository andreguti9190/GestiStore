"""Flujo de pagos de demostración y punto de reemplazo para una pasarela real."""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import PagoSandbox, Producto


@dataclass(frozen=True)
class DemoCardResult:
    brand: str
    last4: str
    status: str
    reason: str = ''


# El navegador convierte exclusivamente estas tarjetas públicas de prueba en
# tokens. El backend nunca recibe PAN, vencimiento ni CVV.
DEMO_CARD_TOKENS = {
    'demo_visa_approved': DemoCardResult('Visa', '1111', 'aprobado'),
    'demo_mastercard_approved': DemoCardResult('Mastercard', '4444', 'aprobado'),
    'demo_amex_approved': DemoCardResult('American Express', '0005', 'aprobado'),
    'demo_visa_pending': DemoCardResult(
        'Visa', '0002', 'pendiente', 'La entidad todavía está procesando el pago.'
    ),
    'demo_mastercard_rejected': DemoCardResult(
        'Mastercard', '5100', 'rechazado', 'Pago rechazado por el emisor de prueba.'
    ),
}


def _release_reserved_stock(payment):
    if payment.stock_liberado:
        return
    for detail in payment.venta.detalles.select_related('producto').all():
        product = Producto.objects.select_for_update().get(pk=detail.producto_id)
        product.stock += detail.cantidad
        product.save(update_fields=['stock'])
    payment.stock_liberado = True


def process_demo_card(reference, user, token):
    """Aplica un token público de sandbox de forma transaccional e idempotente."""
    result = DEMO_CARD_TOKENS.get(token)
    if not result:
        raise ValueError('La tarjeta no pertenece al entorno de demostración.')

    with transaction.atomic():
        payment = (
            PagoSandbox.objects.select_for_update()
            .select_related('venta')
            .get(referencia=reference, venta__usuario=user, proveedor='demopay')
        )
        if payment.estado in {'aprobado', 'rechazado', 'reembolsado'}:
            return payment, False

        payment.marca_tarjeta = result.brand
        payment.ultimos_cuatro = result.last4
        payment.estado = result.status
        payment.motivo = result.reason
        sale = payment.venta

        if result.status == 'aprobado':
            sale.estado_pago = 'pagado'
            sale.estado = 'completada'
            sale.estado_envio = 'preparando'
            payment.aprobado_en = timezone.now()
        elif result.status == 'rechazado':
            sale.estado_pago = 'rechazado'
            sale.estado = 'cancelada'
            sale.estado_envio = 'cancelado'
            _release_reserved_stock(payment)
        else:
            sale.estado_pago = 'procesando'
            sale.estado = 'pendiente'
            sale.estado_envio = 'pendiente'

        sale.save(update_fields=['estado_pago', 'estado', 'estado_envio'])
        payment.save(update_fields=[
            'marca_tarjeta', 'ultimos_cuatro', 'estado', 'motivo',
            'stock_liberado', 'aprobado_en', 'actualizado_en',
        ])
        from .realtime import publish_dashboard_event
        transaction.on_commit(
            lambda: publish_dashboard_event('sale.updated', sale.pk)
        )
        return payment, True


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
