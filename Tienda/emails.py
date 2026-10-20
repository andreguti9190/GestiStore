import ipaddress
import json
import logging
import math
import time
from email.mime.image import MIMEImage
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def mail_configuration_problem():
    if settings.EMAIL_BACKEND != 'django.core.mail.backends.smtp.EmailBackend':
        return 'El backend de correo configurado no envía mensajes por SMTP.'
    if settings.EMAIL_HOST == 'smtp.gmail.com' and (
        not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD
    ):
        return 'Faltan el correo remitente y/o su contraseña de aplicación de Gmail.'
    return None


def _send_templated_email(
    *, subject, recipient, text_template, html_template, context, attachments=(),
):
    if settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend':
        problem = mail_configuration_problem()
        if problem:
            raise ImproperlyConfigured(problem)
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(text_template, context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(render_to_string(html_template, context), 'text/html')
    for attachment in attachments:
        message.attach(attachment)
    sent = message.send(fail_silently=False)
    if sent != 1:
        raise RuntimeError('El servidor de correo no aceptó el mensaje.')
    return sent


def send_login_code(user, code):
    return _send_templated_email(
        subject='Tu código de acceso a AmpereStore',
        recipient=user.email,
        text_template='tienda/emails/codigo_login.txt',
        html_template='tienda/emails/codigo_login.html',
        context={'usuario': user, 'codigo': code, 'minutos': 10},
    )


def _client_ip(request):
    # Cloudflare Tunnel provides this header; ignore forwarded headers from
    # arbitrary clients and validate the value before any lookup.
    candidate = request.META.get('HTTP_CF_CONNECTING_IP', '').strip()
    if not candidate:
        candidate = request.META.get('REMOTE_ADDR', '').strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return ''


def _login_location(ip_address):
    if not ip_address:
        return None
    parsed_ip = ipaddress.ip_address(ip_address)
    if parsed_ip.is_private or parsed_ip.is_loopback or parsed_ip.is_reserved:
        return None
    try:
        template = settings.IP_GEOLOCATION_URL_TEMPLATE
        if not template:
            return None
        url = template.format(ip=ip_address)
        request = Request(url, headers={'User-Agent': 'AmpereStore-Security/1.0'})
        # La consulta se ejecuta mientras se prepara el aviso. En conexiones
        # residenciales o móviles 1,5 segundos resultaba demasiado estricto y
        # hacía desaparecer el mapa aunque el proveedor estuviera disponible.
        with urlopen(request, timeout=4.0) as response:
            data = json.loads(response.read(16384).decode('utf-8'))
        if not isinstance(data, dict) or data.get('error'):
            return None
        city = str(data.get('city') or '').strip()
        region = str(data.get('region') or '').strip()
        country = str(data.get('country_name') or '').strip()
        label = ', '.join(part for part in (city, region, country) if part)
        latitude = float(data['latitude']) if data.get('latitude') is not None else None
        longitude = float(data['longitude']) if data.get('longitude') is not None else None
        if not label:
            return None
        map_url = None
        if latitude is not None and longitude is not None:
            # Una décima de grado mantiene el dato deliberadamente aproximado.
            latitude = round(latitude, 1)
            longitude = round(longitude, 1)
            map_url = (
                f'https://www.openstreetmap.org/?mlat={latitude:.1f}&mlon={longitude:.1f}'
                f'#map=8/{latitude:.1f}/{longitude:.1f}'
            )
        return {
            'label': label,
            'map_url': map_url,
            'latitude': latitude,
            'longitude': longitude,
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        logger.info('No se pudo determinar la ubicación aproximada del inicio de sesión')
        return None


def _map_tile(latitude, longitude, zoom=8):
    latitude = max(-85.0511, min(85.0511, latitude))
    world_size = 2 ** zoom
    x_float = (longitude + 180.0) / 360.0 * world_size
    latitude_radians = math.radians(latitude)
    y_float = (
        1.0 - math.asinh(math.tan(latitude_radians)) / math.pi
    ) / 2.0 * world_size
    x = int(x_float) % world_size
    y = max(0, min(world_size - 1, int(y_float)))
    return x, y, x_float - int(x_float), y_float - int(y_float)


def _read_map_tile(x, y, zoom=8):
    cache_path = (
        Path(settings.BASE_DIR) / '.runtime' / 'map_tiles' /
        str(zoom) / str(x) / f'{y}.png'
    )
    if cache_path.is_file() and time.time() - cache_path.stat().st_mtime < 604800:
        return cache_path.read_bytes()

    request = Request(
        f'https://tile.openstreetmap.org/{zoom}/{x}/{y}.png',
        headers={'User-Agent': 'AmpereStore/1.0 (vista previa de acceso)'},
    )
    with urlopen(request, timeout=5.0) as response:
        contents = response.read(1024 * 1024)

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(contents)
    except OSError:
        logger.info('No se pudo guardar la caché del mapa de inicio de sesión')
    return contents


def _login_map_preview(location):
    if not location or location.get('latitude') is None or location.get('longitude') is None:
        return None
    try:
        x, y, x_fraction, y_fraction = _map_tile(
            float(location['latitude']), float(location['longitude'])
        )
        source = Image.open(BytesIO(_read_map_tile(x, y))).convert('RGB')
        source = source.resize((512, 512), Image.Resampling.LANCZOS)

        marker_x = round(x_fraction * 512)
        marker_y = round(y_fraction * 512)
        crop_top = max(0, min(212, marker_y - 150))
        preview = source.crop((0, crop_top, 512, crop_top + 300))
        marker_y -= crop_top

        draw = ImageDraw.Draw(preview)
        draw.ellipse(
            (marker_x - 13, marker_y - 13, marker_x + 13, marker_y + 13),
            fill='#ffffff', outline='#353166', width=3,
        )
        draw.ellipse(
            (marker_x - 7, marker_y - 7, marker_x + 7, marker_y + 7),
            fill='#d24655',
        )
        draw.rectangle((0, 276, 512, 300), fill='#ffffff')
        draw.text((10, 282), 'Mapa: OpenStreetMap contributors', fill='#353166')

        output = BytesIO()
        preview.save(output, format='PNG', optimize=True)
        image = MIMEImage(output.getvalue(), _subtype='png')
        image.add_header('Content-ID', '<ubicacion-aproximada>')
        image.add_header(
            'Content-Disposition', 'inline', filename='ubicacion-aproximada.png'
        )
        return image
    except (OSError, ValueError, TypeError, KeyError):
        logger.info('No se pudo preparar la vista previa del mapa de acceso')
        return None


def _device_label(request):
    agent = request.META.get('HTTP_USER_AGENT', '').lower()
    if 'iphone' in agent:
        return 'iPhone'
    if 'ipad' in agent:
        return 'iPad'
    if 'android' in agent:
        return 'Android'
    if 'windows' in agent:
        return 'Windows'
    if 'mac os' in agent or 'macintosh' in agent:
        return 'Mac'
    if 'linux' in agent:
        return 'Linux'
    return 'Dispositivo desconocido'


def send_login_notification(request, user, method):
    if not user.email:
        return 0
    ip_address = _client_ip(request)
    location = _login_location(ip_address)
    map_preview = _login_map_preview(location)
    context = {
        'usuario': user,
        'fecha': timezone.now(),
        'dispositivo': _device_label(request),
        'metodo': method,
        'ip': ip_address or 'No disponible',
        'ubicacion': location['label'] if location else 'No disponible',
        'mapa_url': location['map_url'] if location else None,
        'mapa_imagen': 'cid:ubicacion-aproximada' if map_preview else None,
        'ubicacion_nota': (
            'La ubicación se estimó a partir de la IP pública y puede corresponder a la '
            'central del proveedor, especialmente con VPN o redes móviles.'
        ),
    }
    return _send_templated_email(
        subject='Nuevo inicio de sesión en AmpereStore',
        recipient=user.email,
        text_template='tienda/emails/aviso_inicio_sesion.txt',
        html_template='tienda/emails/aviso_inicio_sesion.html',
        context=context,
        attachments=[map_preview] if map_preview else [],
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
