from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def _send_templated_email(*, subject, recipient, text_template, html_template, context):
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(text_template, context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(render_to_string(html_template, context), 'text/html')
    return message.send(fail_silently=False)


def send_login_code(user, code):
    return _send_templated_email(
        subject='Tu código de acceso a AmpereStore',
        recipient=user.email,
        text_template='tienda/emails/codigo_login.txt',
        html_template='tienda/emails/codigo_login.html',
        context={'usuario': user, 'codigo': code, 'minutos': 10},
    )


def send_registration_code(user, code):
    return _send_templated_email(
        subject='Confirmá tu cuenta de AmpereStore',
        recipient=user.email,
        text_template='tienda/emails/codigo_registro.txt',
        html_template='tienda/emails/codigo_registro.html',
        context={'usuario': user, 'codigo': code, 'minutos': 10},
    )


def send_purchase_receipt(venta):
    detalles = list(venta.detalles.select_related('producto').all())
    return _send_templated_email(
        subject=f'Comprobante de compra {venta.codigo} - AmpereStore',
        recipient=venta.usuario.email,
        text_template='tienda/emails/comprobante.txt',
        html_template='tienda/emails/comprobante.html',
        context={'venta': venta, 'detalles': detalles},
    )
