import logging
import json
import math
import secrets
import hashlib
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
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

from .models import CredencialFacial, CredencialPasskey, Producto, Venta, DetalleVenta, Perfil
from .forms import LoginForm, ProductoForm, RegistroForm
from .emails import (
    send_login_code,
    send_login_notification,
    send_purchase_receipt,
    send_registration_code,
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
            _send_login_notice_safely(request, user, 'Contraseña y código por email')
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
        try:
            with transaction.atomic():
                if pending_user:
                    _clear_pending_registration_otp(request)
                usuario = form.save(commit=False)
                usuario.is_active = False
                usuario.save()
                Perfil.objects.update_or_create(
                    usuario=usuario,
                    defaults={
                        'rol': 'operador',
                        'fecha_nacimiento': form.cleaned_data['fecha_nacimiento'],
                        'terminos_aceptados_en': timezone.now(),
                        'terminos_version': TERMS_VERSION,
                    },
                )
                _clear_pending_registration_otp(request)
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
            logger.exception('No se pudo enviar el código de registro')
            _clear_pending_registration_otp(request)
            form.add_error(
                None,
                'No pudimos enviar el código de verificación. Intentá nuevamente en unos minutos.',
            )
        else:
            return redirect('verificar_registro')
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
            _send_login_notice_safely(request, user, 'Verificación de cuenta por email')
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
    })


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
    _send_login_notice_safely(request, saved.usuario, 'Reconocimiento facial')
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
    _send_login_notice_safely(request, saved.usuario, 'Face ID o passkey')
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
    })


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

    metodo = request.POST.get('metodo_pago', 'tarjeta')

    if metodo != 'transferencia':
        numero = request.POST.get('numero_tarjeta', '').replace(' ', '')
        nombre = request.POST.get('nombre_tarjeta', '')
        vencimiento = request.POST.get('vencimiento', '')
        cvv = request.POST.get('cvv', '')

        if len(numero) != 16 or not numero.isdigit():
            messages.error(request, 'El número de tarjeta debe tener 16 dígitos.')
            return redirect('confirmar_compra')
        if not nombre:
            messages.error(request, 'Ingresá el nombre del titular.')
            return redirect('confirmar_compra')
        if len(vencimiento) != 5:
            messages.error(request, 'Ingresá una fecha de vencimiento válida (MM/AA).')
            return redirect('confirmar_compra')
        if len(cvv) not in [3, 4]:
            messages.error(request, 'El CVV debe tener 3 o 4 dígitos.')
            return redirect('confirmar_compra')

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
            estado='completada',
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

    request.session['carrito'] = {}
    request.session.pop('purchase_face_auth', None)
    request.session['ultima_compra'] = venta.codigo

    receipt_sent = False
    if request.user.email:
        try:
            receipt_sent = bool(send_purchase_receipt(venta))
        except Exception:
            logger.exception('No se pudo enviar el comprobante de la venta %s', venta.codigo)
    request.session['comprobante_enviado'] = receipt_sent

    return redirect('compra_exitosa')


@login_required
def compra_exitosa(request):
    codigo = request.session.get('ultima_compra', '')
    venta = Venta.objects.filter(codigo=codigo, usuario=request.user).select_related('usuario').first()
    detalles = venta.detalles.select_related('producto').all() if venta else []
    return render(request, 'tienda/compra_exitosa.html', {
        'venta': venta,
        'detalles': detalles,
        'comprobante_enviado': request.session.pop('comprobante_enviado', None),
    })


# ─── MIS COMPRAS ──────────────────────────────────────────
@login_required
@require_POST
def reenviar_comprobante(request, pk):
    venta = get_object_or_404(
        Venta.objects.select_related('usuario'), pk=pk,
        usuario=request.user, estado='completada',
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
        if not send_purchase_receipt(venta):
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
    ventas = Venta.objects.filter(usuario=request.user, estado='completada')\
        .prefetch_related('detalles__producto').order_by('-fecha_venta')
    return render(request, 'tienda/mis_compras.html', {'ventas': ventas})


# ─── HISTORIAL DE VENTAS (ADMIN) ──────────────────────────
@login_required
@solo_admin
def historial_ventas(request):
    ventas = Venta.objects.filter(estado='completada')\
        .select_related('usuario')\
        .prefetch_related('detalles__producto')\
        .order_by('usuario__username', '-fecha_venta')

    grupos = []
    indice = {}
    for venta in ventas:
        grupo = indice.get(venta.usuario_id)
        if grupo is None:
            grupo = {'usuario': venta.usuario, 'ventas': [], 'total': 0}
            indice[venta.usuario_id] = grupo
            grupos.append(grupo)
        grupo['ventas'].append(venta)
        grupo['total'] += venta.total

    return render(request, 'tienda/historial_ventas.html', {'grupos': grupos})
