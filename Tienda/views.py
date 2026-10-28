import logging
import json
import math
import re
import secrets
import hashlib
import csv
import threading
import unicodedata
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import (
    CredencialFacial, CredencialPasskey, DetalleVenta, PagoSandbox,
    Perfil, Producto, SolicitudDevolucion, Venta,
)
from .forms import LoginForm, ProductoForm, RegistroForm
from .emails import (
    send_login_code,
    send_login_notification,
    send_purchase_receipt,
    send_registration_code,
)
from .realtime import get_dashboard_revision, publish_dashboard_event
from .payments import (
    MercadoPagoError, apply_mercadopago_status, cancel_reserved_payment,
    create_mercadopago_preference, fetch_mercadopago_payment,
    mercado_pago_configured, refund_mercadopago_payment,
    sync_payment_from_admin, validate_mercadopago_signature,
)


logger = logging.getLogger(__name__)

OTP_SESSION_KEYS = (
    'otp_user_id', 'otp_code_hash', 'otp_expires_at', 'otp_attempts',
    'otp_backend', 'otp_next', 'otp_sent_at',
)

REGISTRATION_OTP_SESSION_KEYS = (
    'registration_otp_user_id', 'registration_otp_code_hash',
    'registration_otp_expires_at', 'registration_otp_attempts',
    'registration_otp_sent_at',
)

TERMS_VERSION = '2026-10-19'

ARGENTINA_PROVINCES = {
    '02': 'Ciudad Autónoma de Buenos Aires',
    '06': 'Buenos Aires',
    '10': 'Catamarca',
    '14': 'Córdoba',
    '18': 'Corrientes',
    '22': 'Chaco',
    '26': 'Chubut',
    '30': 'Entre Ríos',
    '34': 'Formosa',
    '38': 'Jujuy',
    '42': 'La Pampa',
    '46': 'La Rioja',
    '50': 'Mendoza',
    '54': 'Misiones',
    '58': 'Neuquén',
    '62': 'Río Negro',
    '66': 'Salta',
    '70': 'San Juan',
    '74': 'San Luis',
    '78': 'Santa Cruz',
    '82': 'Santa Fe',
    '86': 'Santiago del Estero',
    '90': 'Tucumán',
    '94': 'Tierra del Fuego, Antártida e Islas del Atlántico Sur',
}

ARGENTINA_CAPITAL_FALLBACKS = {
    '02': ('Ciudad Autónoma de Buenos Aires', -34.6037, -58.3816),
    '06': ('La Plata', -34.9214, -57.9544),
    '10': ('San Fernando del Valle de Catamarca', -28.4696, -65.7852),
    '14': ('Córdoba', -31.4201, -64.1888),
    '18': ('Corrientes', -27.4692, -58.8306),
    '22': ('Resistencia', -27.4514, -58.9867),
    '26': ('Rawson', -43.3002, -65.1023),
    '30': ('Paraná', -31.7320, -60.5238),
    '34': ('Formosa', -26.1849, -58.1731),
    '38': ('San Salvador de Jujuy', -24.1858, -65.2995),
    '42': ('Santa Rosa', -36.6203, -64.2906),
    '46': ('La Rioja', -29.4131, -66.8558),
    '50': ('Mendoza', -32.8895, -68.8458),
    '54': ('Posadas', -27.3621, -55.9009),
    '58': ('Neuquén', -38.9516, -68.0591),
    '62': ('Viedma', -40.8135, -62.9967),
    '66': ('Salta', -24.7821, -65.4232),
    '70': ('San Juan', -31.5375, -68.5364),
    '74': ('San Luis', -33.3017, -66.3378),
    '78': ('Río Gallegos', -51.6230, -69.2168),
    '82': ('Santa Fe', -31.6333, -60.7000),
    '86': ('Santiago del Estero', -27.7834, -64.2642),
    '90': ('San Miguel de Tucumán', -26.8083, -65.2176),
    '94': ('Ushuaia', -54.8019, -68.3030),
}

PASSKEY_REGISTRATION_SESSION_KEYS = (
    'passkey_registration_challenge', 'passkey_registration_created_at',
    'passkey_registration_rp_id', 'passkey_registration_origin',
)
PASSKEY_AUTHENTICATION_SESSION_KEYS = (
    'passkey_authentication_challenge', 'passkey_authentication_created_at',
    'passkey_authentication_rp_id', 'passkey_authentication_origin', 'passkey_next',
)


class PasswordResetConBaseView(auth_views.PasswordResetView):
    """Usa la URL de la demo para enlaces de email, si fue configurada."""

    def form_valid(self, form):
        self.extra_email_context = {
            **(self.extra_email_context or {}),
            'public_base_url': settings.PUBLIC_BASE_URL,
        }
        return super().form_valid(form)


# ─── DECORADOR ADMIN ──────────────────────────────────────
def solo_admin(view_func):
    def wrapper(request, *args, **kwargs):
        try:
            if request.user.perfil.rol == 'admin':
                return view_func(request, *args, **kwargs)
        except Exception:
            pass
        raise PermissionDenied
    return wrapper


def es_admin(user):
    try:
        return user.perfil.rol == 'admin'
    except Exception:
        return False


def error_403(request, exception=None):
    return render(request, 'tienda/403.html', status=403)


def csrf_failure(request, reason=''):
    """Recupera formularios vencidos sin desactivar la protección CSRF."""
    retry_routes = {
        reverse('login'): 'login',
        reverse('verificar_2fa'): 'verificar_2fa',
        reverse('registro'): 'registro',
        reverse('verificar_registro'): 'verificar_registro',
    }
    route_name = retry_routes.get(request.path)
    if route_name:
        messages.warning(
            request,
            'La página de seguridad había vencido. Volvé a enviar el formulario.',
        )
        return redirect(route_name)

    if request.path in {
        reverse('login_facial'),
        reverse('registrar_rostro'),
    }:
        return JsonResponse({
            'error': 'La sesión de seguridad venció. Recargá la página e intentá nuevamente.'
        }, status=403)

    return render(request, 'tienda/csrf_error.html', status=403)


# ─── INICIO ───────────────────────────────────────────────
@login_required
def inicio(request):
    productos = Producto.objects.filter(activo=True).order_by('-fecha_creacion')
    destacados = productos[:8]
    total_productos = Producto.objects.filter(activo=True).count()
    categorias = Producto.CATEGORIA_CHOICES
    return render(request, 'tienda/inicio.html', {
        'destacados': destacados,
        'total_productos': total_productos,
        'categorias': categorias,
    })


# ─── AUTH ─────────────────────────────────────────────────
def _clear_pending_otp(request):
    for key in OTP_SESSION_KEYS:
        request.session.pop(key, None)


def usuario_requiere_2fa(user):
    """La verificación en dos pasos es una preferencia de cada cuenta."""
    try:
        return bool(user.perfil.verificacion_dos_pasos)
    except (Perfil.DoesNotExist, AttributeError):
        return False


def _masked_email(email):
    local, separator, domain = email.partition('@')
    if not separator:
        return email
    visible = local[:2] if len(local) > 2 else local[:1]
    return f'{visible}{"*" * max(3, len(local) - len(visible))}@{domain}'


def _webauthn_context(request):
    rp_id = settings.WEBAUTHN_RP_ID
    if not rp_id:
        rp_id = request.get_host().split(':', 1)[0].strip('[]')
    origin = settings.WEBAUTHN_ORIGIN or f'{request.scheme}://{request.get_host()}'
    return rp_id, origin


def _store_passkey_challenge(request, prefix, challenge, rp_id, origin):
    request.session[f'{prefix}_challenge'] = bytes_to_base64url(challenge)
    request.session[f'{prefix}_created_at'] = int(timezone.now().timestamp())
    request.session[f'{prefix}_rp_id'] = rp_id
    request.session[f'{prefix}_origin'] = origin


def _consume_passkey_challenge(request, prefix):
    challenge = request.session.pop(f'{prefix}_challenge', None)
    created_at = request.session.pop(f'{prefix}_created_at', 0)
    rp_id = request.session.pop(f'{prefix}_rp_id', None)
    origin = request.session.pop(f'{prefix}_origin', None)
    age = int(timezone.now().timestamp()) - created_at
    if (
        not challenge or not rp_id or not origin or age < 0
        or age > settings.WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS
    ):
        return None
    return base64url_to_bytes(challenge), rp_id, origin


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _preparar_descriptores_faciales(raw_descriptors):
    """Valida las lecturas y devuelve el centroide y cada vector normalizado."""
    if not isinstance(raw_descriptors, list) or not 2 <= len(raw_descriptors) <= 5:
        raise ValueError('Cantidad de capturas inválida')

    descriptors = []
    for raw in raw_descriptors:
        if not isinstance(raw, list) or len(raw) != 128:
            raise ValueError('Descriptor facial inválido')
        descriptor = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError('Descriptor facial inválido')
            value = float(value)
            if not math.isfinite(value) or abs(value) > 10:
                raise ValueError('Descriptor facial inválido')
            descriptor.append(value)
        descriptors.append(descriptor)

    def normalize(vector):
        norm = math.sqrt(sum(value * value for value in vector))
        if norm < 0.01:
            raise ValueError('Descriptor facial inválido')
        return [value / norm for value in vector]

    normalized = [normalize(descriptor) for descriptor in descriptors]
    average = [
        sum(descriptor[index] for descriptor in descriptors) / len(descriptors)
        for index in range(128)
    ]
    centroid = [round(value, 8) for value in normalize(average)]
    return centroid, normalized


def _normalizar_descriptor_facial(raw_descriptors):
    """Compatibilidad interna: devuelve el centroide de varias lecturas."""
    centroid, _normalized = _preparar_descriptores_faciales(raw_descriptors)
    return centroid


def _distancia_facial(left, right):
    if (
        not isinstance(left, list) or len(left) != 128
        or not isinstance(right, list) or len(right) != 128
    ):
        return math.inf
    try:
        return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))
    except (TypeError, ValueError, OverflowError):
        return math.inf


def _capturas_faciales_consistentes(descriptors):
    return all(
        _distancia_facial(descriptors[left], descriptors[right])
        <= settings.FACE_CAPTURE_CONSISTENCY_THRESHOLD
        for left in range(len(descriptors))
        for right in range(left + 1, len(descriptors))
    )


def _face_login_rate_limited(request):
    now = int(timezone.now().timestamp())
    window = settings.FACE_LOGIN_ATTEMPT_WINDOW_SECONDS
    failures = [
        timestamp for timestamp in request.session.get('face_login_failures', [])
        if isinstance(timestamp, int) and now - timestamp < window
    ]
    request.session['face_login_failures'] = failures
    return len(failures) >= settings.FACE_LOGIN_MAX_ATTEMPTS


def _record_face_login_failure(request):
    failures = request.session.get('face_login_failures', [])
    failures.append(int(timezone.now().timestamp()))
    request.session['face_login_failures'] = failures[-settings.FACE_LOGIN_MAX_ATTEMPTS:]


def _clear_pending_registration_otp(request):
    for key in REGISTRATION_OTP_SESSION_KEYS:
        request.session.pop(key, None)


def _issue_registration_code(request, user):
    code = f'{secrets.randbelow(1_000_000):06d}'
    now = timezone.now()
    send_registration_code(user, code)
    request.session['registration_otp_user_id'] = user.pk
    request.session['registration_otp_code_hash'] = make_password(code)
    request.session['registration_otp_expires_at'] = int(
        (now + timedelta(seconds=settings.EMAIL_OTP_EXPIRY_SECONDS)).timestamp()
    )
    request.session['registration_otp_attempts'] = 0
    request.session['registration_otp_sent_at'] = int(now.timestamp())


def _issue_login_code(request, user):
    code = f'{secrets.randbelow(1_000_000):06d}'
    now = timezone.now()
    # Solo reemplazamos el código vigente cuando Gmail aceptó el mensaje.
    send_login_code(user, code)
    request.session['otp_user_id'] = user.pk
    request.session['otp_code_hash'] = make_password(code)
    request.session['otp_expires_at'] = int(
        (now + timedelta(seconds=settings.EMAIL_OTP_EXPIRY_SECONDS)).timestamp()
    )
    request.session['otp_attempts'] = 0
    request.session['otp_sent_at'] = int(now.timestamp())


def _send_login_notice_safely(request, user, method):
    try:
        if not send_login_notification(request, user, method):
            raise RuntimeError('No se pudo enviar el aviso de acceso.')
    except Exception:
        logger.exception('No se pudo enviar el aviso de inicio de sesión al usuario %s', user.pk)
        messages.warning(request, 'Ingresaste correctamente, pero no pudimos enviar el aviso de acceso por email.')


def _send_login_notice_in_background(user_id, request_meta, method):
    """Envía el aviso sin retener la respuesta que fija la cookie de sesión."""
    close_old_connections()
    try:
        user = User.objects.get(pk=user_id)
        send_login_notification(SimpleNamespace(META=request_meta), user, method)
    except Exception:
        logger.exception(
            'No se pudo enviar en segundo plano el aviso de inicio de sesión al usuario %s',
            user_id,
        )
    finally:
        close_old_connections()


def _queue_login_notice(request, user, method):
    """Evita que geolocalización, mapas o SMTP demoren el login.

    El backend de memoria usado por las pruebas se conserva síncrono para que
    sus resultados sean deterministas. El SMTP real se ejecuta en un hilo
    daemon con una copia mínima de los metadatos necesarios.
    """
    if settings.EMAIL_BACKEND != 'django.core.mail.backends.smtp.EmailBackend':
        _send_login_notice_safely(request, user, method)
        return

    request_meta = {
        key: request.META.get(key, '')
        for key in ('HTTP_CF_CONNECTING_IP', 'REMOTE_ADDR', 'HTTP_USER_AGENT')
    }
    worker = threading.Thread(
        target=_send_login_notice_in_background,
        args=(user.pk, request_meta, method),
        name=f'login-notice-{user.pk}',
        daemon=True,
    )
    try:
        worker.start()
    except RuntimeError:
        logger.exception('No se pudo iniciar el envío del aviso de acceso')


def _cart_fingerprint(cart):
    normalized = sorted(
        (str(item.get('producto_id', key)), int(item.get('cantidad', 0)))
        for key, item in cart.items()
    )
    return hashlib.sha256(json.dumps(normalized).encode('utf-8')).hexdigest()


def _valid_purchase_face_proof(request, cart):
    proof = request.session.get('purchase_face_auth') or {}
    return (
        proof.get('user_id') == request.user.pk
        and proof.get('cart') == _cart_fingerprint(cart)
        and isinstance(proof.get('expires'), int)
        and proof['expires'] >= int(timezone.now().timestamp())
    )


def _has_recent_login_code(request, user):
    now = int(timezone.now().timestamp())
    sent_at = request.session.get('otp_sent_at', 0)
    return (
        request.session.get('otp_user_id') == user.pk
        and bool(request.session.get('otp_code_hash'))
        and request.session.get('otp_expires_at', 0) > now
        and now - sent_at < settings.EMAIL_OTP_RESEND_SECONDS
    )


@never_cache
def iniciar_sesion(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    form = LoginForm(request=request, data=request.POST or None)
    next_url = request.POST.get('next') or request.GET.get('next') or reverse('inicio')
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse('inicio')

    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        if not usuario_requiere_2fa(user):
            # La cuenta eligió no usar el segundo factor: alcanza con la
            # contraseña y se evita el paso adicional en cada ingreso.
            login(request, user)
            request.session.save()
            _queue_login_notice(request, user, 'Contraseña')
            messages.success(request, 'Inicio de sesión confirmado.')
            return redirect(next_url)

        if not user.email:
            form.add_error(None, 'Tu cuenta no tiene un email registrado. Contactá al administrador.')
        else:
            # Evita emails duplicados si el navegador repite el formulario.
            if _has_recent_login_code(request, user):
                return redirect('verificar_2fa')
            _clear_pending_otp(request)
            request.session['otp_backend'] = user.backend
            request.session['otp_next'] = next_url
            try:
                _issue_login_code(request, user)
            except Exception:
                logger.exception('No se pudo enviar el código de acceso al usuario %s', user.pk)
                _clear_pending_otp(request)
                form.add_error(None, 'No pudimos enviar el código. Intentá nuevamente en unos minutos.')
            else:
                return redirect('verificar_2fa')

    return render(request, 'tienda/login.html', {'form': form, 'next': next_url})


@never_cache
def verificar_2fa(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    user_id = request.session.get('otp_user_id')
    expires_at = request.session.get('otp_expires_at', 0)
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if not user or not request.session.get('otp_code_hash'):
        _clear_pending_otp(request)
        messages.info(request, 'Primero ingresá tu usuario y contraseña.')
        return redirect('login')

    if int(timezone.now().timestamp()) > expires_at:
        _clear_pending_otp(request)
        messages.error(request, 'El código venció. Iniciá sesión nuevamente.')
        return redirect('login')

    if request.method == 'POST' and request.POST.get('action') == 'resend':
        seconds_since_send = int(timezone.now().timestamp()) - request.session.get('otp_sent_at', 0)
        if seconds_since_send < settings.EMAIL_OTP_RESEND_SECONDS:
            messages.info(request, f'Esperá {settings.EMAIL_OTP_RESEND_SECONDS - seconds_since_send} segundos para reenviar.')
        else:
            try:
                _issue_login_code(request, user)
            except Exception:
                logger.exception('No se pudo reenviar el código de acceso al usuario %s', user.pk)
                messages.error(request, 'No pudimos reenviar el código. Intentá nuevamente.')
            else:
                messages.success(request, 'Te enviamos un código nuevo.')
        return redirect('verificar_2fa')

    error = None
    if request.method == 'POST':
        code = request.POST.get('codigo', '').strip()
        attempts = request.session.get('otp_attempts', 0) + 1
        request.session['otp_attempts'] = attempts

        if attempts > settings.EMAIL_OTP_MAX_ATTEMPTS:
            _clear_pending_otp(request)
            messages.error(request, 'Superaste el límite de intentos. Iniciá sesión nuevamente.')
            return redirect('login')

        if code.isdigit() and len(code) == 6 and check_password(
            code, request.session['otp_code_hash']
        ):
            backend = request.session.get('otp_backend')
            next_url = request.session.get('otp_next', reverse('inicio'))
            _clear_pending_otp(request)
            login(request, user, backend=backend)
            # Guardamos la sesión antes de cualquier tarea de red. Si Gmail o
            # la geolocalización demoran, la autenticación ya quedó persistida.
            request.session.save()
            _queue_login_notice(request, user, 'Contraseña y código por email')
            messages.success(request, 'Inicio de sesión confirmado.')
            return redirect(next_url)

        remaining = settings.EMAIL_OTP_MAX_ATTEMPTS - attempts
        error = f'El código no es válido. Te quedan {remaining} intentos.'

    return render(request, 'tienda/verificar_2fa.html', {
        'email_oculto': _masked_email(user.email),
        'error': error,
    })


@never_cache
def registro(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    pending_user = None
    if request.method == 'POST':
        # Permite reiniciar una alta que quedó sin verificar (por ejemplo, si
        # se cerró la pestaña o hubo un doble envío). Solo se retoma cuando
        # coinciden usuario y email; una cuenta verificada nunca se toca.
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        pending_user = User.objects.filter(
            username__iexact=username,
            email__iexact=email,
            is_active=False,
            perfil__isnull=False,
            perfil__registro_verificado_en__isnull=True,
        ).first()
    form = RegistroForm(request.POST or None, pending_user=pending_user)
    if request.method == 'POST' and form.is_valid():
        usar_2fa = bool(form.cleaned_data.get('activar_2fa'))
        try:
            with transaction.atomic():
                if pending_user:
                    _clear_pending_registration_otp(request)
                usuario = form.save(commit=False)
                usuario.is_active = not usar_2fa
                usuario.save()
                Perfil.objects.update_or_create(
                    usuario=usuario,
                    defaults={
                        'rol': 'operador',
                        'fecha_nacimiento': form.cleaned_data['fecha_nacimiento'],
                        'responsable_nombre': form.cleaned_data.get('responsable_nombre', '').strip(),
                        'responsable_dni': form.cleaned_data.get('responsable_dni', '').strip(),
                        'responsable_parentesco': form.cleaned_data.get('responsable_parentesco', '').strip(),
                        'terminos_aceptados_en': timezone.now(),
                        'terminos_version': TERMS_VERSION,
                        'verificacion_dos_pasos': usar_2fa,
                    },
                )
                _clear_pending_registration_otp(request)
                if usar_2fa:
                    _issue_registration_code(request, usuario)
        except IntegrityError:
            # Dos envíos simultáneos pueden validar el mismo usuario antes de
            # que el primero termine de guardarlo. La restricción de la base
            # de datos sigue siendo la última defensa, pero mostramos un error
            # útil en lugar de atribuírselo al envío del email.
            logger.info(
                'Registro duplicado rechazado para el usuario %s',
                form.cleaned_data.get('username'),
            )
            pending_user = User.objects.filter(
                username__iexact=form.cleaned_data.get('username', ''),
                email__iexact=form.cleaned_data.get('email', ''),
                is_active=False,
                perfil__isnull=False,
                perfil__registro_verificado_en__isnull=True,
            ).first()
            if pending_user:
                try:
                    _clear_pending_registration_otp(request)
                    _issue_registration_code(request, pending_user)
                except Exception:
                    logger.exception(
                        'No se pudo recuperar el registro duplicado del usuario %s',
                        pending_user.pk,
                    )
                    _clear_pending_registration_otp(request)
                    form.add_error(
                        None,
                        'La cuenta se creó, pero no pudimos enviar el código. Intentá nuevamente.',
                    )
                else:
                    return redirect('verificar_registro')
            else:
                form.add_error(
                    'username',
                    'Ese nombre de usuario acaba de registrarse. Elegí otro o iniciá sesión.',
                )
        except Exception:
            logger.exception('No se pudo completar el registro')
            _clear_pending_registration_otp(request)
            form.add_error(
                None,
                (
                    'No pudimos enviar el código de verificación. Intentá nuevamente en unos minutos.'
                    if usar_2fa else
                    'No pudimos crear la cuenta. Intentá nuevamente en unos minutos.'
                ),
            )
        else:
            if usar_2fa:
                return redirect('verificar_registro')
            login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
            request.session.save()
            _queue_login_notice(request, usuario, 'Registro sin código adicional')
            messages.success(request, 'Tu cuenta fue creada y ya está lista para usar.')
            return redirect('inicio')
    return render(request, 'tienda/registro.html', {'form': form})


@never_cache
def verificar_registro(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    user_id = request.session.get('registration_otp_user_id')
    expires_at = request.session.get('registration_otp_expires_at', 0)
    user = User.objects.filter(pk=user_id, is_active=False).first()
    if not user or not request.session.get('registration_otp_code_hash'):
        _clear_pending_registration_otp(request)
        messages.info(request, 'Completá el registro para recibir un código de verificación.')
        return redirect('registro')

    if int(timezone.now().timestamp()) > expires_at:
        # La cuenta nunca fue habilitada: se elimina para que la persona pueda
        # comenzar nuevamente con el mismo usuario y email.
        user.delete()
        _clear_pending_registration_otp(request)
        messages.error(request, 'El código venció. Completá el registro nuevamente.')
        return redirect('registro')

    if request.method == 'POST' and request.POST.get('action') == 'resend':
        now = int(timezone.now().timestamp())
        seconds_since_send = now - request.session.get('registration_otp_sent_at', 0)
        if seconds_since_send < settings.EMAIL_OTP_RESEND_SECONDS:
            messages.info(
                request,
                f'Esperá {settings.EMAIL_OTP_RESEND_SECONDS - seconds_since_send} segundos para reenviar.',
            )
        else:
            try:
                _issue_registration_code(request, user)
            except Exception:
                logger.exception('No se pudo reenviar el código de registro al usuario %s', user.pk)
                messages.error(request, 'No pudimos reenviar el código. Intentá nuevamente.')
            else:
                messages.success(request, 'Te enviamos un código nuevo.')
        return redirect('verificar_registro')

    error = None
    if request.method == 'POST':
        code = request.POST.get('codigo', '').strip()
        attempts = request.session.get('registration_otp_attempts', 0) + 1
        request.session['registration_otp_attempts'] = attempts

        if code.isdigit() and len(code) == 6 and check_password(
            code, request.session['registration_otp_code_hash']
        ):
            with transaction.atomic():
                user.is_active = True
                user.save(update_fields=['is_active'])
                user.perfil.registro_verificado_en = timezone.now()
                user.perfil.save(update_fields=['registro_verificado_en'])
            _clear_pending_registration_otp(request)
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            request.session.save()
            _queue_login_notice(request, user, 'Verificación de cuenta por email')
            messages.success(request, 'Tu cuenta fue verificada y ya está lista para usar.')
            return redirect('inicio')

        if attempts >= settings.EMAIL_OTP_MAX_ATTEMPTS:
            user.delete()
            _clear_pending_registration_otp(request)
            messages.error(request, 'Superaste el límite de intentos. Completá el registro nuevamente.')
            return redirect('registro')

        remaining = settings.EMAIL_OTP_MAX_ATTEMPTS - attempts
        error = f'El código no es válido. Te quedan {remaining} intentos.'

    return render(request, 'tienda/verificar_registro.html', {
        'email_oculto': _masked_email(user.email),
        'error': error,
    })


def terminos_y_condiciones(request):
    return render(request, 'tienda/terminos_y_condiciones.html', {
        'terms_version': TERMS_VERSION,
    })


def descargar_certificado_local(request):
    certificate_path = settings.BASE_DIR / '.certificados' / 'amperestore-ca.cer'
    if not certificate_path.is_file():
        raise Http404('El certificado local todavía no fue generado.')
    return FileResponse(
        certificate_path.open('rb'),
        as_attachment=True,
        filename='amperestore-ca.cer',
        content_type='application/x-x509-ca-cert',
    )


# ─── RECONOCIMIENTO FACIAL CON CÁMARA ────────────────────
@login_required
def seguridad_cuenta(request):
    return render(request, 'tienda/seguridad_cuenta.html', {
        'credenciales': request.user.credenciales_passkey.all(),
        'credencial_facial': CredencialFacial.objects.filter(usuario=request.user).first(),
        'verificacion_dos_pasos': usuario_requiere_2fa(request.user),
    })


@login_required
@require_POST
def configurar_verificacion_dos_pasos(request):
    perfil, _created = Perfil.objects.get_or_create(
        usuario=request.user,
        defaults={'rol': 'admin' if request.user.is_staff else 'operador'},
    )
    activar = request.POST.get('activar') == '1'
    if activar and not request.user.email:
        messages.error(
            request,
            'Necesitás tener un email registrado para activar la verificación en dos pasos.',
        )
        return redirect('seguridad_cuenta')

    perfil.verificacion_dos_pasos = activar
    perfil.save(update_fields=['verificacion_dos_pasos'])
    if activar:
        messages.success(
            request,
            'Verificación en dos pasos activada. Te pediremos un código al iniciar '
            'sesión y una confirmación antes de comprar.',
        )
    else:
        messages.info(
            request,
            'Verificación en dos pasos desactivada. Vas a ingresar solamente con tu contraseña.',
        )
    return redirect('seguridad_cuenta')


@login_required
@require_POST
def registrar_rostro(request):
    payload = _json_body(request)
    if not payload or payload.get('consent') is not True:
        return JsonResponse({
            'error': 'Necesitamos tu consentimiento para registrar el reconocimiento facial.'
        }, status=400)
    try:
        descriptor, captures = _preparar_descriptores_faciales(payload.get('descriptors'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'No pudimos leer el rostro. Intentá nuevamente.'}, status=400)
    if not _capturas_faciales_consistentes(captures):
        return JsonResponse({
            'error': 'Las capturas no fueron consistentes. Debe aparecer una sola persona y mantener el rostro quieto.'
        }, status=400)

    CredencialFacial.objects.update_or_create(
        usuario=request.user,
        defaults={
            'descriptor': descriptor,
            'modelo': settings.FACE_RECOGNITION_MODEL_VERSION,
            'consentimiento_en': timezone.now(),
        },
    )
    return JsonResponse({
        'ok': True,
        'message': 'Tu rostro quedó registrado. Ya podés probar el acceso facial.',
    })


@login_required
@require_POST
def eliminar_rostro(request):
    CredencialFacial.objects.filter(usuario=request.user).delete()
    messages.success(request, 'El reconocimiento facial fue eliminado de tu cuenta.')
    return redirect('seguridad_cuenta')


@require_POST
def login_facial(request):
    if request.user.is_authenticated:
        return JsonResponse({
            'error': 'Ya hay una sesión iniciada. Cerrala antes de probar otro acceso facial.'
        }, status=400)
    if _face_login_rate_limited(request):
        return JsonResponse({
            'error': 'Demasiados intentos. Esperá cinco minutos o ingresá con tu contraseña.'
        }, status=429)

    payload = _json_body(request) or {}
    username = str(payload.get('username') or '').strip()
    next_url = payload.get('next') or reverse('inicio')
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse('inicio')

    try:
        _probe_centroid, probe_captures = _preparar_descriptores_faciales(
            payload.get('descriptors')
        )
    except (TypeError, ValueError):
        return JsonResponse({'error': 'No pudimos leer el rostro. Intentá nuevamente.'}, status=400)
    if not _capturas_faciales_consistentes(probe_captures):
        _record_face_login_failure(request)
        return JsonResponse({
            'error': 'Las lecturas del rostro no fueron consistentes. Mirá al frente e intentá nuevamente.'
        }, status=400)

    saved = CredencialFacial.objects.select_related('usuario').filter(
        usuario__username=username,
        usuario__is_active=True,
    ).first()
    if saved and saved.modelo != settings.FACE_RECOGNITION_MODEL_VERSION:
        return JsonResponse({
            'error': 'Por una mejora de seguridad, tenés que actualizar tu rostro desde la sección Seguridad ingresando primero con contraseña.'
        }, status=400)

    distances = (
        [_distancia_facial(saved.descriptor, capture) for capture in probe_captures]
        if saved else []
    )
    if (
        not saved or not distances
        or any(distance > settings.FACE_RECOGNITION_THRESHOLD for distance in distances)
    ):
        _record_face_login_failure(request)
        return JsonResponse({
            'error': 'No pudimos reconocer el rostro para ese usuario. Podés volver a intentar o usar tu contraseña.'
        }, status=400)

    request.session.pop('face_login_failures', None)
    saved.ultimo_uso = timezone.now()
    saved.save(update_fields=['ultimo_uso'])
    login(request, saved.usuario, backend='django.contrib.auth.backends.ModelBackend')
    request.session.save()
    _queue_login_notice(request, saved.usuario, 'Reconocimiento facial')
    return JsonResponse({'ok': True, 'redirect': next_url})


# ─── PASSKEYS (COMPATIBILIDAD CON CUENTAS EXISTENTES) ────
@login_required
@require_POST
def passkey_registro_opciones(request):
    rp_id, origin = _webauthn_context(request)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(request.user.pk).encode('utf-8'),
        user_name=request.user.username,
        user_display_name=request.user.get_full_name() or request.user.username,
        timeout=settings.WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS * 1000,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(item.credential_id))
            for item in request.user.credenciales_passkey.all()
        ],
    )
    _store_passkey_challenge(
        request, 'passkey_registration', options.challenge, rp_id, origin
    )
    return JsonResponse(json.loads(options_to_json(options)))


@login_required
@require_POST
def passkey_registro_verificar(request):
    payload = _json_body(request)
    challenge_data = _consume_passkey_challenge(request, 'passkey_registration')
    if not payload or not challenge_data or 'credential' not in payload:
        return JsonResponse({'error': 'La solicitud venció. Intentá registrar el dispositivo nuevamente.'}, status=400)

    challenge, rp_id, origin = challenge_data
    try:
        verification = verify_registration_response(
            credential=payload['credential'],
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
        nombre = str(payload.get('name') or 'Este dispositivo').strip()[:80]
        transports = payload['credential'].get('response', {}).get('transports', [])
        if not isinstance(transports, list):
            transports = []
        CredencialPasskey.objects.create(
            usuario=request.user,
            nombre=nombre or 'Este dispositivo',
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            transports=transports,
            device_type=verification.credential_device_type.value,
            backed_up=verification.credential_backed_up,
        )
    except IntegrityError:
        return JsonResponse({'error': 'Esta passkey ya está registrada.'}, status=400)
    except (WebAuthnException, KeyError, TypeError, ValueError):
        logger.exception('Falló la verificación de una nueva passkey para %s', request.user.pk)
        return JsonResponse({'error': 'No pudimos verificar Face ID o la passkey.'}, status=400)

    return JsonResponse({'ok': True, 'message': 'Face ID o passkey quedó habilitado.'})


@login_required
@require_POST
def eliminar_passkey(request, pk):
    credential = get_object_or_404(CredencialPasskey, pk=pk, usuario=request.user)
    credential.delete()
    messages.success(request, 'El acceso con Face ID o passkey fue eliminado de ese dispositivo.')
    return redirect('seguridad_cuenta')


@require_POST
def passkey_login_opciones(request):
    if request.user.is_authenticated:
        return JsonResponse({'redirect': reverse('inicio')})
    if not CredencialPasskey.objects.exists():
        return JsonResponse({'error': 'Todavía no hay una passkey registrada.'}, status=400)

    payload = _json_body(request) or {}
    next_url = payload.get('next') or reverse('inicio')
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse('inicio')

    rp_id, origin = _webauthn_context(request)
    options = generate_authentication_options(
        rp_id=rp_id,
        timeout=settings.WEBAUTHN_CHALLENGE_TIMEOUT_SECONDS * 1000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _store_passkey_challenge(
        request, 'passkey_authentication', options.challenge, rp_id, origin
    )
    request.session['passkey_next'] = next_url
    return JsonResponse(json.loads(options_to_json(options)))


@require_POST
def passkey_login_verificar(request):
    if request.user.is_authenticated:
        return JsonResponse({'redirect': reverse('inicio')})

    payload = _json_body(request)
    next_url = request.session.pop('passkey_next', reverse('inicio'))
    challenge_data = _consume_passkey_challenge(request, 'passkey_authentication')
    if not payload or not challenge_data or 'credential' not in payload:
        return JsonResponse({'error': 'La solicitud venció. Intentá ingresar nuevamente.'}, status=400)

    try:
        credential_id = base64url_to_bytes(payload['credential']['id'])
        saved = CredencialPasskey.objects.select_related('usuario').get(
            credential_id=credential_id,
            usuario__is_active=True,
        )
    except (CredencialPasskey.DoesNotExist, KeyError, TypeError, ValueError):
        return JsonResponse({'error': 'La passkey no está registrada en AmpereStore.'}, status=400)

    challenge, rp_id, origin = challenge_data
    try:
        verification = verify_authentication_response(
            credential=payload['credential'],
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(saved.public_key),
            credential_current_sign_count=saved.sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError):
        logger.exception('Falló el ingreso por passkey para la credencial %s', saved.pk)
        return JsonResponse({'error': 'Face ID o la passkey no pudo verificarse.'}, status=400)

    saved.sign_count = verification.new_sign_count
    saved.device_type = verification.credential_device_type.value
    saved.backed_up = verification.credential_backed_up
    saved.ultimo_uso = timezone.now()
    saved.save(update_fields=['sign_count', 'device_type', 'backed_up', 'ultimo_uso'])
    login(request, saved.usuario, backend='django.contrib.auth.backends.ModelBackend')
    request.session.save()
    _queue_login_notice(request, saved.usuario, 'Face ID o passkey')
    return JsonResponse({'ok': True, 'redirect': next_url})


# ─── PRODUCTOS ────────────────────────────────────────────
@login_required
def lista_productos(request):
    q = request.GET.get('q', '')
    categoria = request.GET.get('categoria', '')
    productos = Producto.objects.filter(activo=True)

    if q:
        productos = productos.filter(
            models_Q_nombre_descripcion(q)
        )
    if categoria:
        productos = productos.filter(categoria=categoria)

    return render(request, 'tienda/lista_productos.html', {
        'productos': productos,
        'q': q,
        'categoria_actual': categoria,
        'CATEGORIA_CHOICES': Producto.CATEGORIA_CHOICES,
    })


def models_Q_nombre_descripcion(q):
    from django.db.models import Q
    return Q(nombre__icontains=q) | Q(descripcion__icontains=q)


@login_required
def detalle_producto(request, pk):
    producto = get_object_or_404(Producto, pk=pk, activo=True)
    relacionados = Producto.objects.filter(categoria=producto.categoria, activo=True)\
        .exclude(pk=producto.pk)[:4]
    return render(request, 'tienda/detalle_producto.html', {
        'producto': producto,
        'relacionados': relacionados,
    })


@login_required
@solo_admin
def crear_producto(request):
    form = ProductoForm(request.POST or None, request.FILES or None)
    if form.is_valid():
        form.save()
        messages.success(request, 'Producto creado.')
        return redirect('lista_productos')
    return render(request, 'tienda/form_producto.html', {'form': form, 'titulo': 'Nuevo Producto'})


@login_required
@solo_admin
def editar_producto(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    form = ProductoForm(request.POST or None, request.FILES or None, instance=producto)
    if form.is_valid():
        form.save()
        messages.success(request, 'Producto actualizado.')
        return redirect('lista_productos')
    return render(request, 'tienda/form_producto.html', {
        'form': form, 'titulo': 'Editar Producto', 'producto': producto
    })


@login_required
@solo_admin
def eliminar_producto(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    if request.method == 'POST':
        producto.activo = False
        producto.save()
        messages.success(request, 'Producto eliminado.')
        return redirect('lista_productos')
    return render(request, 'tienda/confirmar_eliminar.html', {'objeto': producto})


# ─── CARRITO ──────────────────────────────────────────────
@login_required
def agregar_carrito(request, pk):
    if es_admin(request.user):
        return redirect('historial_ventas')
    producto = get_object_or_404(Producto, pk=pk)
    if request.method == 'POST':
        try:
            cantidad = int(request.POST.get('cantidad', 1))
        except (ValueError, TypeError):
            cantidad = 1
        if cantidad < 1:
            cantidad = 1
        if cantidad > producto.stock:
            messages.error(request, f'Solo hay {producto.stock} unidades disponibles.')
            return redirect('detalle_producto', pk=pk)

        carrito = request.session.get('carrito', {})
        key = str(pk)
        if key in carrito:
            nueva_cantidad = carrito[key]['cantidad'] + cantidad
            if nueva_cantidad > producto.stock:
                messages.error(request, f'No podés superar el stock disponible ({producto.stock}).')
                return redirect('detalle_producto', pk=pk)
            carrito[key]['cantidad'] = nueva_cantidad
        else:
            carrito[key] = {
                'producto_id': pk,
                'producto_nombre': producto.nombre,
                'producto_precio': float(producto.precio),
                'producto_imagen': producto.imagen.url if producto.imagen else '',
                'producto_categoria': producto.get_categoria_display(),
                'cantidad': cantidad,
            }
        request.session['carrito'] = carrito
        messages.success(request, 'Producto agregado al carrito.')
        return redirect('ver_carrito')
    return redirect('detalle_producto', pk=pk)


@login_required
def ver_carrito(request):
    if es_admin(request.user):
        return redirect('historial_ventas')
    carrito = request.session.get('carrito', {})
    items = []
    total = 0
    for key, item in carrito.items():
        subtotal = item['producto_precio'] * item['cantidad']
        total += subtotal
        items.append({**item, 'subtotal': subtotal, 'key': key})
    return render(request, 'tienda/carrito.html', {'items': items, 'total': total})


@login_required
def eliminar_carrito(request, key):
    if es_admin(request.user):
        return redirect('historial_ventas')
    carrito = request.session.get('carrito', {})
    if key in carrito:
        del carrito[key]
        request.session['carrito'] = carrito
        messages.success(request, 'Producto eliminado del carrito.')
    return redirect('ver_carrito')


@login_required
def confirmar_compra(request):
    if es_admin(request.user):
        return redirect('historial_ventas')
    carrito = request.session.get('carrito', {})
    if not carrito:
        messages.error(request, 'Tu carrito está vacío.')
        return redirect('lista_productos')
    request.session.pop('purchase_face_auth', None)

    items = []
    total = 0
    for key, item in carrito.items():
        subtotal = item['producto_precio'] * item['cantidad']
        total += subtotal
        items.append({**item, 'subtotal': subtotal, 'key': key})

    return render(request, 'tienda/pago.html', {
        'items': items,
        'total': total,
        'has_face_credential': CredencialFacial.objects.filter(usuario=request.user).exists(),
        'requiere_verificacion_compra': usuario_requiere_2fa(request.user),
        'argentina_provinces': [
            {
                'id': province_id,
                'nombre': province_name,
                'lat': ARGENTINA_CAPITAL_FALLBACKS[province_id][1],
                'lng': ARGENTINA_CAPITAL_FALLBACKS[province_id][2],
            }
            for province_id, province_name in sorted(
                ARGENTINA_PROVINCES.items(), key=lambda item: item[1]
            )
        ],
        'mercadopago_enabled': mercado_pago_configured(),
        'mercadopago_test_mode': settings.MERCADOPAGO_MODE == 'test',
        'esri_geocode_url': settings.ESRI_GEOCODE_URL,
    })


@login_required
@require_GET
def localidades_argentina(request):
    """Devuelve localidades oficiales de una provincia con un respaldo mínimo."""
    province_id = request.GET.get('provincia', '').strip()
    province_name = ARGENTINA_PROVINCES.get(province_id)
    if not province_name:
        return JsonResponse({'error': 'La provincia seleccionada no es válida.'}, status=400)

    cache_key = f'georef-localidades-v2-{province_id}'
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    params = urlencode({
        'provincia': province_id,
        'max': 5000,
        'orden': 'nombre',
    })
    url = f'{settings.GEOREF_API_BASE_URL}/localidades?{params}'
    try:
        georef_request = Request(url, headers={
            'Accept': 'application/json',
            'User-Agent': 'AmpereStore/1.0 (selector de envios)',
        })
        with urlopen(georef_request, timeout=8) as response:
            payload = json.load(response)

        localities = []
        seen = set()
        for locality in payload.get('localidades', []):
            name = str(locality.get('nombre') or '').strip()
            department = str(
                (locality.get('departamento') or {}).get('nombre') or ''
            ).strip()
            locality_id = str(locality.get('id') or '').strip()
            centroid = locality.get('centroide') or {}
            unique_key = (name.casefold(), department.casefold())
            if not name or not locality_id or unique_key in seen:
                continue
            seen.add(unique_key)
            label = name
            if department and department.casefold() != name.casefold():
                label = f'{name} — {department}'
            localities.append({
                'id': locality_id,
                'nombre': name,
                'etiqueta': label,
                'departamento': department,
                'lat': centroid.get('lat'),
                'lng': centroid.get('lon'),
            })
        if not localities:
            raise ValueError('Georef no devolvió localidades.')

        result = {
            'provincia': {'id': province_id, 'nombre': province_name},
            'fuente': 'georef',
            'atribucion': 'Servicio Georef — argentina.gob.ar/georef',
            'centro': {
                'lat': ARGENTINA_CAPITAL_FALLBACKS[province_id][1],
                'lng': ARGENTINA_CAPITAL_FALLBACKS[province_id][2],
            },
            'localidades': localities,
        }
        cache.set(cache_key, result, 60 * 60 * 24)
        return JsonResponse(result)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        logger.warning('No se pudo consultar Georef para la provincia %s', province_id)
        fallback_name, latitude, longitude = ARGENTINA_CAPITAL_FALLBACKS[province_id]
        result = {
            'provincia': {'id': province_id, 'nombre': province_name},
            'fuente': 'respaldo',
            'aviso': 'El catálogo oficial no respondió. Mostramos la capital provincial como respaldo.',
            'centro': {'lat': latitude, 'lng': longitude},
            'localidades': [{
                'id': f'fallback-{province_id}',
                'nombre': fallback_name,
                'etiqueta': fallback_name,
                'departamento': '',
                'lat': latitude,
                'lng': longitude,
            }],
        }
        cache.set(cache_key, result, 60 * 5)
        return JsonResponse(result)


@login_required
@require_GET
def ubicacion_argentina(request):
    """Resuelve localidad y provincia a partir de las coordenadas del mapa."""
    try:
        latitude = Decimal(request.GET.get('lat', ''))
        longitude = Decimal(request.GET.get('lng', ''))
        if not (Decimal('-90') <= latitude <= Decimal('90')
                and Decimal('-180') <= longitude <= Decimal('180')):
            raise ValueError
    except (ValueError, ArithmeticError):
        return JsonResponse({
            'ok': False,
            'error': 'Las coordenadas indicadas no son válidas.',
        }, status=400)

    cache_key = f'georef-ubicacion-v1-{latitude:.4f}-{longitude:.4f}'
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    params = urlencode({'lat': str(latitude), 'lon': str(longitude)})
    url = f'{settings.GEOREF_API_BASE_URL}/ubicacion?{params}'
    try:
        georef_request = Request(url, headers={
            'Accept': 'application/json',
            'User-Agent': 'AmpereStore/1.0 (punto de entrega)',
        })
        with urlopen(georef_request, timeout=6) as response:
            payload = json.load(response)

        location = payload.get('ubicacion') or {}
        province_data = location.get('provincia') or {}
        locality_data = location.get('localidad') or {}
        census_data = location.get('localidad_censal') or {}
        municipality_data = (
            location.get('municipio')
            or location.get('gobierno_local')
            or {}
        )
        department_data = location.get('departamento') or {}
        province = str(province_data.get('nombre') or '').strip()
        locality = str(locality_data.get('nombre') or '').strip()
        if not locality:
            locality = str(census_data.get('nombre') or '').strip()
        if not locality:
            locality = str(municipality_data.get('nombre') or '').strip()
        department = str(department_data.get('nombre') or '').strip()
        if not locality:
            locality = department
        if not province and not locality:
            raise ValueError('Georef no devolvió una ubicación.')

        result = {
            'ok': True,
            'localidad': locality,
            'provincia': province,
            'departamento': department,
            'fuente': 'georef',
        }
        cache.set(cache_key, result, 60 * 60 * 24)
        return JsonResponse(result)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        logger.warning(
            'No se pudo resolver la ubicación %.6f, %.6f con Georef',
            latitude, longitude,
        )
        result = {
            'ok': False,
            'localidad': '',
            'provincia': '',
            'departamento': '',
            'fuente': 'no-disponible',
        }
        cache.set(cache_key, result, 60 * 5)
        return JsonResponse(result)


@login_required
@require_GET
def direccion_argentina(request):
    """Ubica una dirección escrita dentro de la provincia elegida."""
    address = ' '.join(request.GET.get('direccion', '').split())[:180]
    postal_code = ''.join(request.GET.get('codigo_postal', '').split())[:12]
    province_id = request.GET.get('provincia', '').strip()
    province_name = ARGENTINA_PROVINCES.get(province_id)
    if len(address) < 5 or not province_name:
        return JsonResponse({
            'ok': False,
            'error': 'Ingresá una dirección y elegí una provincia válida.',
        }, status=400)

    address_cache_value = f'{address.casefold()}|{postal_code.casefold()}'
    address_hash = hashlib.sha256(address_cache_value.encode('utf-8')).hexdigest()[:24]
    cache_key = f'geocode-direccion-v3-{province_id}-{address_hash}'
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    params = urlencode({
        'direccion': address,
        'provincia': province_id,
        'max': 10,
    })
    url = f'{settings.GEOREF_API_BASE_URL}/direcciones?{params}'
    try:
        georef_request = Request(url, headers={
            'Accept': 'application/json',
            'User-Agent': 'AmpereStore/1.0 (ubicacion de envios)',
        })
        try:
            with urlopen(georef_request, timeout=8) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            logger.warning(
                'Georef no pudo geocodificar la direccion "%s" en %s; se usara Esri',
                address, province_id,
            )
            payload = {'direcciones': []}

        matches = []
        seen_departments = set()
        for direction in payload.get('direcciones', []):
            location = direction.get('ubicacion') or {}
            try:
                latitude = float(location.get('lat'))
                longitude = float(location.get('lon'))
            except (TypeError, ValueError):
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            locality_data = direction.get('localidad') or {}
            census_data = direction.get('localidad_censal') or {}
            municipality_data = (
                direction.get('municipio')
                or direction.get('gobierno_local')
                or {}
            )
            department_data = direction.get('departamento') or {}
            locality = str(locality_data.get('nombre') or '').strip()
            if not locality:
                locality = str(census_data.get('nombre') or '').strip()
            if not locality:
                locality = str(municipality_data.get('nombre') or '').strip()
            department = str(department_data.get('nombre') or '').strip()
            if not locality:
                locality = department
            duplicate_key = (department or locality).casefold()
            if duplicate_key in seen_departments:
                continue
            seen_departments.add(duplicate_key)
            matches.append({
                'ok': True,
                'lat': latitude,
                'lng': longitude,
                'localidad': locality,
                'provincia': province_name,
                'departamento': department,
                'nomenclatura': str(direction.get('nomenclatura') or '').strip()[:250],
                'fuente': 'georef',
            })

        if len(matches) == 1:
            result = matches[0]
            cache.set(cache_key, result, 60 * 60 * 24)
            return JsonResponse(result)

        # Georef suele reconocer la calle y la localidad pero dejar lat/lon en
        # null, especialmente en PBA. Tambien puede devolver varias calles con
        # el mismo nombre. Esri usa el codigo postal para desempatar y permite
        # mostrar una ubicacion aproximada en vez de ocultar todo el mapa.
        esri_params = urlencode({
            'SingleLine': ', '.join(filter(None, (
                address, postal_code, province_name, 'Argentina',
            ))),
            'countryCode': 'ARG',
            'maxLocations': 5,
            'outFields': 'Match_addr,City,Region,Postal',
            'f': 'json',
        })
        esri_url = f'{settings.ESRI_GEOCODE_URL}?{esri_params}'
        esri_request = Request(esri_url, headers={
            'Accept': 'application/json',
            'User-Agent': 'AmpereStore/1.0 (ubicacion de envios)',
        })
        try:
            with urlopen(esri_request, timeout=8) as response:
                esri_payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
            logger.warning(
                'Esri no pudo geocodificar la direccion "%s" en %s',
                address, province_id,
            )
            esri_payload = {'candidates': []}

        def normalized(value):
            text = unicodedata.normalize('NFKD', str(value or ''))
            return ''.join(char for char in text if not unicodedata.combining(char)).casefold()

        def region_matches(region):
            region_value = normalized(region)
            if province_id == '02':
                return 'ciudad autonoma de buenos aires' in region_value
            if province_id == '06':
                return (
                    'provincia de buenos aires' in region_value
                    or region_value == 'buenos aires'
                )
            province_value = normalized(province_name)
            return province_value in region_value or region_value in province_value

        requested_postal_digits = ''.join(re.findall(r'\d', postal_code))
        requested_numbers = re.findall(r'(?<!\d)\d{1,6}(?!\d)', address)
        candidates = []
        for candidate in esri_payload.get('candidates', []):
            location = candidate.get('location') or {}
            attributes = candidate.get('attributes') or {}
            try:
                latitude = float(location.get('y'))
                longitude = float(location.get('x'))
                score = float(candidate.get('score') or 0)
            except (TypeError, ValueError):
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            if score < 75 or not region_matches(attributes.get('Region')):
                continue
            match_address = str(
                attributes.get('Match_addr') or candidate.get('address') or ''
            ).strip()
            candidate_postal_digits = ''.join(
                re.findall(r'\d', str(attributes.get('Postal') or ''))
            )
            postal_match = bool(
                requested_postal_digits
                and candidate_postal_digits == requested_postal_digits
            )
            number_match = any(
                re.search(rf'(?<!\d){re.escape(number)}(?!\d)', match_address)
                for number in requested_numbers
            )
            rank = (1000 if postal_match else 0) + (500 if number_match else 0) + score
            candidates.append((rank, {
                'ok': True,
                'lat': latitude,
                'lng': longitude,
                'localidad': str(attributes.get('City') or '').strip() or province_name,
                'provincia': province_name,
                'departamento': '',
                'nomenclatura': match_address[:250],
                'fuente': 'esri',
                'precision': 'exacta' if number_match else 'aproximada',
            }))

        if candidates:
            result = max(candidates, key=lambda item: item[0])[1]
            cache.set(cache_key, result, 60 * 60 * 24)
            return JsonResponse(result)

        fallback_locality, fallback_latitude, fallback_longitude = (
            ARGENTINA_CAPITAL_FALLBACKS[province_id]
        )
        result = {
            'ok': True,
            'lat': fallback_latitude,
            'lng': fallback_longitude,
            'localidad': fallback_locality,
            'provincia': province_name,
            'departamento': '',
            'nomenclatura': f'Punto aproximado en {province_name}',
            'message': (
                'No pudimos ubicar la direccion exacta. '
                'Podes arrastrar el marcador para ajustar el punto.'
            ),
            'fuente': 'respaldo-provincial',
            'precision': 'provincia',
        }
        cache.set(cache_key, result, 60 * 10)
        return JsonResponse(result)

        if len(matches) > 1:
            message = (
                'Encontramos varias localidades con esa dirección. '
                'Revisá el código postal o continuá con la dirección escrita.'
            )
        else:
            message = 'No encontramos esa dirección dentro de la provincia seleccionada.'
        result = {
            'ok': False,
            'ambiguo': len(matches) > 1,
            'localidad': '',
            'provincia': province_name,
            'departamento': '',
            'message': message,
            'fuente': 'no-disponible',
        }
        cache.set(cache_key, result, 60 * 10)
        return JsonResponse(result)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        logger.warning('No se pudo geocodificar la dirección "%s" en %s', address, province_id)
        result = {
            'ok': False,
            'localidad': '',
            'provincia': province_name,
            'departamento': '',
            'message': 'El servicio de mapas no respondió en este momento.',
            'fuente': 'no-disponible',
        }
        cache.set(cache_key, result, 60 * 5)
        return JsonResponse(result)


@login_required
@require_POST
def verificar_rostro_compra(request):
    carrito = request.session.get('carrito', {})
    if not carrito:
        return JsonResponse({'error': 'Tu carrito está vacío.'}, status=400)
    if _face_login_rate_limited(request):
        return JsonResponse({
            'error': 'Demasiados intentos. Esperá cinco minutos e intentá nuevamente.'
        }, status=429)

    payload = _json_body(request) or {}
    try:
        _centroid, captures = _preparar_descriptores_faciales(payload.get('descriptors'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'No pudimos leer el rostro. Intentá nuevamente.'}, status=400)
    if not _capturas_faciales_consistentes(captures):
        _record_face_login_failure(request)
        return JsonResponse({
            'error': 'Las lecturas del rostro no fueron consistentes. Mirá al frente e intentá nuevamente.'
        }, status=400)

    saved = CredencialFacial.objects.filter(usuario=request.user).first()
    if not saved:
        return JsonResponse({
            'error': 'No hay un rostro registrado para esta cuenta. Elegí confirmar con tu contraseña.'
        }, status=400)
    if saved.modelo != settings.FACE_RECOGNITION_MODEL_VERSION:
        return JsonResponse({
            'error': 'Actualizá tu rostro desde Seguridad antes de usarlo para confirmar compras.'
        }, status=400)
    distances = [_distancia_facial(saved.descriptor, capture) for capture in captures]
    if any(distance > settings.FACE_RECOGNITION_THRESHOLD for distance in distances):
        _record_face_login_failure(request)
        return JsonResponse({'error': 'El rostro no coincide con esta cuenta.'}, status=400)

    request.session.pop('face_login_failures', None)
    request.session['purchase_face_auth'] = {
        'user_id': request.user.pk,
        'cart': _cart_fingerprint(carrito),
        'expires': int(timezone.now().timestamp()) + settings.PURCHASE_FACE_AUTH_SECONDS,
    }
    return JsonResponse({
        'ok': True,
        'message': 'Rostro confirmado. Ahora podés confirmar la compra.',
    })


@login_required
def procesar_pago(request):
    if es_admin(request.user):
        return redirect('historial_ventas')
    if request.method != 'POST':
        return redirect('ver_carrito')

    carrito = request.session.get('carrito', {})
    if not carrito:
        return redirect('lista_productos')

    if usuario_requiere_2fa(request.user):
        verification_method = request.POST.get('verification_method', '')
        if verification_method == 'password':
            account_password = request.POST.get('account_password', '')
            if not account_password or not request.user.check_password(account_password):
                messages.error(request, 'La contraseña de tu cuenta no es correcta.')
                return redirect('confirmar_compra')
        elif verification_method == 'face':
            if not _valid_purchase_face_proof(request, carrito):
                request.session.pop('purchase_face_auth', None)
                messages.error(request, 'Verificá tu rostro nuevamente para confirmar esta compra.')
                return redirect('confirmar_compra')
        else:
            messages.error(request, 'Elegí cómo querés confirmar tu identidad.')
            return redirect('confirmar_compra')

    metodo = 'mercadopago'
    if request.POST.get('metodo_pago', 'mercadopago') != metodo:
        messages.error(request, 'Por ahora solo aceptamos pagos con Mercado Pago.')
        return redirect('confirmar_compra')
    if not mercado_pago_configured():
        messages.error(request, 'Mercado Pago todavía no está configurado por completo.')
        return redirect('confirmar_compra')

    tipo_entrega = request.POST.get('tipo_entrega', 'retiro')
    if tipo_entrega not in dict(Venta.TIPO_ENTREGA_CHOICES):
        messages.error(request, 'El tipo de entrega seleccionado no es válido.')
        return redirect('confirmar_compra')

    entrega = {
        'direccion_entrega': '', 'entrega_localidad': '', 'entrega_provincia': '',
        'entrega_codigo_postal': '', 'entrega_latitud': None, 'entrega_longitud': None,
    }
    if tipo_entrega == 'envio':
        entrega['direccion_entrega'] = request.POST.get('direccion_entrega', '').strip()[:250]
        entrega['entrega_localidad'] = request.POST.get('entrega_localidad', '').strip()[:100]
        entrega['entrega_provincia'] = request.POST.get('entrega_provincia', '').strip()[:100]
        entrega['entrega_codigo_postal'] = request.POST.get('entrega_codigo_postal', '').strip()[:12]
        if not all((entrega['direccion_entrega'], entrega['entrega_provincia'],
                    entrega['entrega_codigo_postal'])):
            messages.error(request, 'Completá la dirección, provincia y código postal.')
            return redirect('confirmar_compra')
        if not entrega['entrega_localidad']:
            entrega['entrega_localidad'] = entrega['entrega_provincia']
        latitude_raw = request.POST.get('entrega_latitud', '').strip()
        longitude_raw = request.POST.get('entrega_longitud', '').strip()
        if latitude_raw and longitude_raw:
            try:
                latitude = Decimal(latitude_raw)
                longitude = Decimal(longitude_raw)
                if not (Decimal('-90') <= latitude <= Decimal('90')
                        and Decimal('-180') <= longitude <= Decimal('180')):
                    raise ValueError
            except (ValueError, ArithmeticError):
                # El mapa es una ayuda opcional: la dirección escrita sigue siendo válida.
                pass
            else:
                entrega['entrega_latitud'] = latitude
                entrega['entrega_longitud'] = longitude


    # La venta y el descuento de stock se confirman como una sola operación.
    with transaction.atomic():
        productos = {}
        total = 0
        for item in carrito.values():
            producto = get_object_or_404(
                Producto.objects.select_for_update(),
                pk=item['producto_id'],
            )
            if item['cantidad'] > producto.stock:
                messages.error(request, f'No hay stock suficiente de "{producto.nombre}".')
                return redirect('ver_carrito')
            productos[producto.pk] = producto
            total += producto.precio * item['cantidad']

        venta = Venta.objects.create(
            usuario=request.user,
            total=total,
            metodo_pago=metodo,
            estado='pendiente',
            estado_pago='pendiente',
            estado_envio='pendiente',
            tipo_entrega=tipo_entrega,
            **entrega,
        )
        payment = PagoSandbox.objects.create(
            venta=venta,
            proveedor='mercadopago',
        )

        for item in carrito.values():
            producto = productos[item['producto_id']]
            DetalleVenta.objects.create(
                venta=venta,
                producto=producto,
                cantidad=item['cantidad'],
                precio_unitario=producto.precio,
            )
            producto.stock -= item['cantidad']
            producto.save(update_fields=['stock'])

        transaction.on_commit(
            lambda: publish_dashboard_event('sale.created', venta.pk)
        )

    try:
        checkout_url = create_mercadopago_preference(payment, request)
    except MercadoPagoError as error:
        cancel_reserved_payment(payment, error)
        messages.error(request, str(error))
        return redirect('confirmar_compra')

    request.session['carrito'] = {}
    request.session.pop('purchase_face_auth', None)
    request.session['ultima_compra'] = venta.codigo
    request.session['comprobante_enviado'] = None

    return redirect(checkout_url)


def _send_purchase_receipt_once(venta):
    payment = PagoSandbox.objects.filter(venta=venta).first()
    if payment and payment.comprobante_enviado_en:
        return True
    if not venta.usuario.email:
        return False
    try:
        sent = bool(send_purchase_receipt(venta))
    except Exception:
        logger.exception('No se pudo enviar el comprobante de la venta %s', venta.codigo)
        return False
    if sent and payment:
        payment.comprobante_enviado_en = timezone.now()
        payment.save(update_fields=['comprobante_enviado_en', 'actualizado_en'])
    return sent


@login_required
@never_cache
def mercadopago_retorno(request):
    """Vuelve de Checkout Pro y confirma el estado consultando la API."""
    sale_code = request.GET.get('external_reference', '').strip()
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id')
    payment = get_object_or_404(
        PagoSandbox.objects.select_related('venta', 'venta__usuario'),
        venta__codigo=sale_code,
        venta__usuario=request.user,
        proveedor='mercadopago',
    )
    request.session['ultima_compra'] = payment.venta.codigo
    request.session['comprobante_enviado'] = None
    if not payment_id:
        messages.info(request, 'Volviste de Mercado Pago, pero el pago todavía no informó una operación.')
        return redirect('compra_exitosa')
    try:
        payload = fetch_mercadopago_payment(payment_id)
        payment, _changed = apply_mercadopago_status(payment, payload)
    except MercadoPagoError as error:
        messages.error(request, str(error))
        return redirect('compra_exitosa')
    if payment.estado == 'aprobado':
        request.session['comprobante_enviado'] = _send_purchase_receipt_once(payment.venta)
    elif payment.estado == 'procesando':
        messages.info(request, 'Mercado Pago está procesando el pago. Se actualizará automáticamente.')
    return redirect('compra_exitosa')


@csrf_exempt
@require_POST
def mercadopago_webhook(request):
    """Recibe Webhooks firmados y usa la API como fuente de verdad."""
    try:
        payload = json.loads(request.body or b'{}')
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({'ok': False}, status=400)
    if payload.get('type') != 'payment':
        return JsonResponse({'ok': True})
    data_id = str(request.GET.get('data.id') or (payload.get('data') or {}).get('id') or '')
    if not validate_mercadopago_signature(
        request.headers.get('x-signature', ''),
        request.headers.get('x-request-id', ''),
        data_id,
    ):
        return JsonResponse({'ok': False}, status=401)
    try:
        resource = fetch_mercadopago_payment(data_id)
        sale_code = str(resource.get('external_reference') or '')
        payment = PagoSandbox.objects.select_related('venta').get(
            venta__codigo=sale_code,
            proveedor='mercadopago',
        )
        payment, changed = apply_mercadopago_status(payment, resource)
        if changed and payment.estado == 'aprobado':
            _send_purchase_receipt_once(payment.venta)
    except PagoSandbox.DoesNotExist:
        return JsonResponse({'ok': True})
    except MercadoPagoError:
        logger.warning('No se pudo sincronizar el pago Mercado Pago %s', data_id)
        return JsonResponse({'ok': False}, status=502)
    return JsonResponse({'ok': True})


@login_required
def compra_exitosa(request):
    codigo = request.session.get('ultima_compra', '')
    venta = (
        Venta.objects.filter(codigo=codigo, usuario=request.user)
        .select_related('usuario')
        .first()
    )
    detalles = venta.detalles.select_related('producto').all() if venta else []
    payment = PagoSandbox.objects.filter(venta=venta).first() if venta else None
    return render(request, 'tienda/compra_exitosa.html', {
        'venta': venta,
        'detalles': detalles,
        'payment': payment,
        'comprobante_enviado': request.session.pop('comprobante_enviado', None),
    })


# ─── MIS COMPRAS ──────────────────────────────────────────
@login_required
@require_POST
def reenviar_comprobante(request, pk):
    venta = get_object_or_404(
        Venta.objects.select_related('usuario'), pk=pk,
        usuario=request.user, estado='completada', estado_pago='pagado',
    )
    now = int(timezone.now().timestamp())
    last_sent = request.session.get('receipt_last_sent_at', 0)
    if now - last_sent < 60:
        messages.info(request, 'Esperá un minuto antes de pedir otro comprobante.')
        return redirect('mis_compras')
    if not request.user.email:
        messages.error(request, 'Tu cuenta no tiene un correo registrado. Contactá al administrador.')
        return redirect('mis_compras')
    try:
        if not _send_purchase_receipt_once(venta):
            raise RuntimeError('No se pudo enviar el comprobante.')
    except Exception:
        logger.exception('No se pudo reenviar el comprobante de la venta %s', venta.codigo)
        messages.error(request, 'No pudimos enviar el comprobante. Contactá al administrador para revisar el correo de la tienda.')
    else:
        request.session['receipt_last_sent_at'] = now
        messages.success(request, f'Comprobante enviado a {request.user.email}. Revisá también Spam.')
    return redirect('mis_compras')


@login_required
def mis_compras(request):
    if es_admin(request.user):
        return redirect('historial_ventas')
    ventas = Venta.objects.filter(usuario=request.user)\
        .select_related('devolucion').prefetch_related('detalles__producto').order_by('-fecha_venta')
    return render(request, 'tienda/mis_compras.html', {'ventas': ventas})


@login_required
@require_POST
def solicitar_devolucion(request, pk):
    venta = get_object_or_404(Venta, pk=pk, usuario=request.user)
    if venta.estado_pago != 'pagado' or venta.estado_envio != 'entregado':
        messages.error(request, 'La devolución se habilita cuando el pedido pagado figura como entregado.')
        return redirect('mis_compras')
    motivo = request.POST.get('motivo', '')
    if motivo not in dict(SolicitudDevolucion.MOTIVO_CHOICES):
        messages.error(request, 'Elegí un motivo de devolución válido.')
        return redirect('mis_compras')
    _return, created = SolicitudDevolucion.objects.get_or_create(
        venta=venta,
        defaults={
            'motivo': motivo,
            'detalle': request.POST.get('detalle', '').strip()[:600],
        },
    )
    if created:
        publish_dashboard_event('return.created', venta.pk)
        messages.success(request, 'Recibimos tu solicitud de devolución. Podés seguirla desde esta pantalla.')
    else:
        messages.info(request, 'Este pedido ya tiene una solicitud de devolución.')
    return redirect('mis_compras')


@login_required
@solo_admin
@require_POST
def resolver_devolucion(request, pk):
    decision = request.POST.get('decision', '')
    if decision not in {'aprobada', 'rechazada'}:
        messages.error(request, 'La decisión seleccionada no es válida.')
        return redirect('historial_ventas')
    if decision == 'aprobada':
        preview = get_object_or_404(
            SolicitudDevolucion.objects.select_related('venta'),
            pk=pk,
            estado='solicitada',
        )
        external_payment = PagoSandbox.objects.filter(
            venta=preview.venta,
            proveedor='mercadopago',
        ).first()
        if external_payment:
            try:
                refund_mercadopago_payment(external_payment)
            except MercadoPagoError as error:
                messages.error(request, f'No se aprobó la devolución: {error}')
                return redirect('historial_ventas')
    try:
        with transaction.atomic():
            devolucion = get_object_or_404(
                SolicitudDevolucion.objects.select_for_update().select_related('venta'),
                pk=pk,
                estado='solicitada',
            )
            devolucion.estado = decision
            devolucion.respuesta = request.POST.get('respuesta', '').strip()[:300]
            devolucion.resuelta_en = timezone.now()
            devolucion.save(update_fields=['estado', 'respuesta', 'resuelta_en', 'actualizada_en'])
            venta = Venta.objects.select_for_update().get(pk=devolucion.venta_id)
            if decision == 'aprobada':
                sync_payment_from_admin(venta, 'reembolsado')
                venta.estado_pago = 'reembolsado'
                venta.estado = 'cancelada'
                venta.estado_envio = 'cancelado'
                venta.save(update_fields=['estado_pago', 'estado', 'estado_envio'])
            sale_id = venta.pk
            transaction.on_commit(lambda: publish_dashboard_event('return.updated', sale_id))
    except Http404:
        messages.error(request, 'La solicitud ya fue resuelta o no existe.')
    else:
        messages.success(request, f'Devolución {devolucion.get_estado_display().lower()}.')
    return redirect('historial_ventas')


@require_POST
def asistente_consulta(request):
    """Asistente determinístico: responde sólo intenciones conocidas y datos locales."""
    intent = request.POST.get('intent', '').strip()
    if intent == 'pagos':
        answer = ('Podés pagar con Mercado Pago, que se abre en su sitio seguro. '
                  'La tienda no recibe ni guarda los datos de tu tarjeta.')
    elif intent == 'envios':
        answer = ('Elegí envío a domicilio o retiro al finalizar la compra. '
                  'El estado y el código de seguimiento aparecen en Mis compras.')
    elif intent == 'devoluciones':
        answer = ('Cuando un pedido pagado figure como entregado, podés solicitar su devolución '
                  'desde Mis compras y seguir la respuesta del vendedor.')
    elif intent == 'stock':
        available = Producto.objects.filter(activo=True, stock__gt=0).count()
        answer = f'Hay {available} productos con stock disponible en este momento.'
    elif intent == 'mi_pedido':
        if not request.user.is_authenticated:
            answer = 'Iniciá sesión para consultar el estado de tu último pedido.'
        else:
            sale = Venta.objects.filter(usuario=request.user).order_by('-fecha_venta').first()
            answer = (f'Tu último pedido {sale.codigo} tiene pago {sale.get_estado_pago_display().lower()} '
                      f'y envío {sale.get_estado_envio_display().lower()}.' if sale
                      else 'Todavía no registramos compras en tu cuenta.')
    else:
        return JsonResponse({'error': 'Elegí una de las consultas disponibles.'}, status=400)
    return JsonResponse({'answer': answer})


# ─── HISTORIAL DE VENTAS (ADMIN) ──────────────────────────
@login_required
@solo_admin
def historial_ventas(request):
    if request.method == 'POST':
        estado_pago = request.POST.get('estado_pago')
        estado_envio = request.POST.get('estado_envio')
        transportista = request.POST.get('transportista', '').strip()[:80]
        tracking = request.POST.get('tracking', '').strip()[:80]
        if estado_pago not in dict(Venta.ESTADO_PAGO_CHOICES):
            messages.error(request, 'El estado de pago seleccionado no es válido.')
        elif estado_envio not in dict(Venta.ESTADO_ENVIO_CHOICES):
            messages.error(request, 'El estado de envío seleccionado no es válido.')
        else:
            try:
                with transaction.atomic():
                    venta = get_object_or_404(
                        Venta.objects.select_for_update(),
                        pk=request.POST.get('venta_id'),
                    )
                    was_paid = venta.estado_pago == 'pagado'
                    if estado_envio == 'cancelado' and estado_pago in {'pendiente', 'procesando'}:
                        estado_pago = 'rechazado'
                    venta.estado_pago = estado_pago
                    venta.estado_envio = estado_envio
                    venta.transportista = transportista
                    venta.tracking = tracking
                    if estado_envio == 'cancelado' or estado_pago in {'rechazado', 'reembolsado'}:
                        venta.estado = 'cancelada'
                    elif estado_pago == 'pagado':
                        venta.estado = 'completada'
                    else:
                        venta.estado = 'pendiente'
                    sync_payment_from_admin(venta, estado_pago)
                    venta.save(update_fields=[
                        'estado_pago', 'estado_envio', 'estado', 'transportista', 'tracking',
                    ])
                    sale_id = venta.pk
                    transaction.on_commit(
                        lambda: publish_dashboard_event('sale.updated', sale_id)
                    )
            except ValueError as error:
                messages.error(request, str(error))
            else:
                if estado_pago == 'pagado' and not was_paid:
                    _send_purchase_receipt_once(venta)
                messages.success(request, f'Pedido {venta.codigo} actualizado correctamente.')
        query = request.POST.get('return_query', '')
        return redirect(f"{reverse('historial_ventas')}?{query}" if query else 'historial_ventas')

    now = timezone.now()
    period = request.GET.get('periodo', '30d')
    period_days = {'hoy': 1, '7d': 7, '30d': 30, '90d': 90}
    if period == 'personalizado':
        try:
            start_date = timezone.datetime.strptime(request.GET.get('desde', ''), '%Y-%m-%d').date()
            end_date = timezone.datetime.strptime(request.GET.get('hasta', ''), '%Y-%m-%d').date()
            if end_date < start_date:
                raise ValueError
        except ValueError:
            period = '30d'
            start_date = timezone.localdate(now) - timedelta(days=29)
            end_date = timezone.localdate(now)
            messages.warning(request, 'El rango de fechas no era válido. Mostramos los últimos 30 días.')
    elif period == 'todo':
        oldest = Venta.objects.order_by('fecha_venta').values_list('fecha_venta', flat=True).first()
        start_date = timezone.localdate(oldest) if oldest else timezone.localdate(now)
        end_date = timezone.localdate(now)
    else:
        days = period_days.get(period, 30)
        period = period if period in period_days else '30d'
        end_date = timezone.localdate(now)
        start_date = end_date - timedelta(days=days - 1)

    start = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end = timezone.make_aware(timezone.datetime.combine(end_date + timedelta(days=1), timezone.datetime.min.time()))
    duration = end - start
    previous_start, previous_end = start - duration, start

    base = Venta.objects.select_related(
        'usuario', 'pago_sandbox', 'devolucion',
    ).prefetch_related('detalles__producto')
    current = list(base.filter(fecha_venta__gte=start, fecha_venta__lt=end).order_by('-fecha_venta'))
    previous = list(base.filter(fecha_venta__gte=previous_start, fecha_venta__lt=previous_end))

    def metrics(rows):
        paid = [sale for sale in rows if sale.estado == 'completada' and sale.estado_pago == 'pagado']
        total = sum((sale.total for sale in paid), Decimal('0'))
        profit = Decimal('0')
        for sale in paid:
            for detail in sale.detalles.all():
                cost = detail.producto.costo
                if cost is None:
                    cost = detail.precio_unitario * Decimal('0.70')
                profit += (detail.precio_unitario - cost) * detail.cantidad
        return {'sales': total, 'profit': profit, 'orders': len(rows),
                'ticket': total / len(paid) if paid else Decimal('0')}

    current_metrics, previous_metrics = metrics(current), metrics(previous)

    def variation(value, old):
        if old == 0:
            return 100 if value else 0
        return round(float((value - old) / old * 100), 1)

    metric_cards = [
        {'key': 'sales', 'label': 'Ventas totales', 'value': current_metrics['sales'], 'money': True,
         'variation': variation(current_metrics['sales'], previous_metrics['sales'])},
        {'key': 'profit', 'label': 'Ganancia estimada', 'value': current_metrics['profit'], 'money': True,
         'variation': variation(current_metrics['profit'], previous_metrics['profit'])},
        {'key': 'orders', 'label': 'Pedidos recibidos', 'value': current_metrics['orders'], 'money': False,
         'variation': variation(current_metrics['orders'], previous_metrics['orders'])},
        {'key': 'ticket', 'label': 'Ticket promedio', 'value': current_metrics['ticket'], 'money': True,
         'variation': variation(current_metrics['ticket'], previous_metrics['ticket'])},
    ]

    span_days = max((end_date - start_date).days + 1, 1)
    bucket = max(1, math.ceil(span_days / 15))
    sales_series = []
    cursor = start_date
    while cursor <= end_date:
        bucket_end = min(cursor + timedelta(days=bucket - 1), end_date)
        amount = sum((sale.total for sale in current
                      if sale.estado == 'completada' and sale.estado_pago == 'pagado'
                      and cursor <= timezone.localdate(sale.fecha_venta) <= bucket_end), Decimal('0'))
        label = cursor.strftime('%d/%m') if bucket == 1 else f"{cursor.strftime('%d/%m')}–{bucket_end.strftime('%d/%m')}"
        sales_series.append({'label': label, 'value': float(amount)})
        cursor = bucket_end + timedelta(days=1)

    shipping_counts = {key: 0 for key, _ in Venta.ESTADO_ENVIO_CHOICES}
    for sale in current:
        shipping_counts[sale.estado_envio] += 1
    shipping_chart = [
        {'key': key, 'label': label, 'value': shipping_counts[key]}
        for key, label in Venta.ESTADO_ENVIO_CHOICES
    ]
    shipping_map = [
        {
            'id': sale.pk,
            'codigo': sale.codigo,
            'cliente': sale.usuario.get_full_name() or sale.usuario.username,
            'estado': sale.get_estado_envio_display(),
            'estado_key': sale.estado_envio,
            'direccion': ', '.join(filter(None, [
                sale.direccion_entrega, sale.entrega_localidad, sale.entrega_provincia,
            ])),
            'lat': float(sale.entrega_latitud),
            'lng': float(sale.entrega_longitud),
            'tracking': sale.tracking,
            'transportista': sale.transportista,
        }
        for sale in current
        if sale.tipo_entrega == 'envio'
        and sale.entrega_latitud is not None and sale.entrega_longitud is not None
        and sale.estado_envio != 'cancelado'
    ]

    product_totals, category_totals = {}, {}
    for sale in current:
        if sale.estado != 'completada' or sale.estado_pago != 'pagado':
            continue
        for detail in sale.detalles.all():
            item = product_totals.setdefault(detail.producto_id, {
                'producto': detail.producto, 'units': 0, 'revenue': Decimal('0')})
            item['units'] += detail.cantidad
            item['revenue'] += detail.subtotal
            category = detail.producto.get_categoria_display()
            category_totals[category] = category_totals.get(category, Decimal('0')) + detail.subtotal
    top_products = sorted(product_totals.values(), key=lambda item: item['revenue'], reverse=True)[:5]
    category_chart = [
        {'label': label, 'value': float(value)}
        for label, value in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:6]
    ]

    query = request.GET.get('q', '').strip()
    shipping_filter = request.GET.get('envio', '')
    payment_filter = request.GET.get('pago', '')
    sort = request.GET.get('orden', '-fecha')
    filtered = base.filter(fecha_venta__gte=start, fecha_venta__lt=end)
    if query:
        filtered = filtered.filter(
            Q(codigo__icontains=query) | Q(usuario__username__icontains=query)
            | Q(usuario__email__icontains=query) | Q(detalles__producto__nombre__icontains=query)
            | Q(detalles__producto__sku__icontains=query)
        ).distinct()
    if shipping_filter in dict(Venta.ESTADO_ENVIO_CHOICES):
        filtered = filtered.filter(estado_envio=shipping_filter)
    if payment_filter in dict(Venta.ESTADO_PAGO_CHOICES):
        filtered = filtered.filter(estado_pago=payment_filter)
    sort_map = {'-fecha': '-fecha_venta', 'fecha': 'fecha_venta', '-total': '-total',
                'total': 'total', 'cliente': 'usuario__username', '-cliente': '-usuario__username'}
    filtered = filtered.order_by(sort_map.get(sort, '-fecha_venta'))
    page_obj = Paginator(filtered, 8).get_page(request.GET.get('page'))

    inventory_alerts = list(Producto.objects.filter(activo=True, stock__lte=5).order_by('stock', 'nombre')[:6])
    total_products = Producto.objects.filter(activo=True).count()
    out_of_stock = Producto.objects.filter(activo=True, stock=0).count()
    active_customers = len({sale.usuario_id for sale in current})
    pending_returns = list(
        SolicitudDevolucion.objects.select_related('venta', 'venta__usuario')
        .filter(estado='solicitada').order_by('-creada_en')
    )
    recent_activity = []
    for sale in current[:5]:
        recent_activity.append({
            'kind': 'order', 'title': f'Pedido {sale.codigo}',
            'text': f'{sale.usuario.get_full_name() or sale.usuario.username} · {sale.get_estado_envio_display()}',
            'date': sale.fecha_venta,
        })
    for product in inventory_alerts[:3]:
        recent_activity.append({
            'kind': 'stock', 'title': 'Alerta de inventario',
            'text': f'{product.nombre}: {product.stock} unidades', 'date': product.fecha_creacion,
        })
    recent_activity.sort(key=lambda item: item['date'], reverse=True)

    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'tienda/dashboard_vendedor.html', {
        'metric_cards': metric_cards, 'sales_series': sales_series,
        'shipping_chart': shipping_chart, 'shipping_map': shipping_map,
        'category_chart': category_chart,
        'top_products': top_products, 'inventory_alerts': inventory_alerts,
        'page_obj': page_obj, 'period': period, 'start_date': start_date,
        'end_date': end_date, 'shipping_choices': Venta.ESTADO_ENVIO_CHOICES,
        'payment_choices': Venta.ESTADO_PAGO_CHOICES, 'query_without_page': params.urlencode(),
        'total_products': total_products, 'out_of_stock': out_of_stock,
        'active_customers': active_customers, 'recent_activity': recent_activity,
        'pending_returns': pending_returns,
        'has_estimated_costs': Producto.objects.filter(costo__isnull=True).exists(),
        'dashboard_revision': get_dashboard_revision(),
    })


@login_required
@solo_admin
def exportar_ventas_csv(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="reporte-ventas-amperestore.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Pedido', 'Fecha', 'Cliente', 'Email', 'Total', 'Pago', 'Envío', 'Método'])
    ventas = Venta.objects.select_related('usuario').order_by('-fecha_venta')
    for venta in ventas:
        writer.writerow([
            venta.codigo, timezone.localtime(venta.fecha_venta).strftime('%d/%m/%Y %H:%M'),
            venta.usuario.get_full_name() or venta.usuario.username, venta.usuario.email,
            venta.total, venta.get_estado_pago_display(), venta.get_estado_envio_display(),
            venta.get_metodo_pago_display(),
        ])
    return response
