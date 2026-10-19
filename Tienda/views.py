import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .models import Producto, Venta, DetalleVenta, Perfil
from .forms import LoginForm, ProductoForm, RegistroForm
from .emails import send_login_code, send_purchase_receipt, send_registration_code


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


def _has_recent_login_code(request, user):
    now = int(timezone.now().timestamp())
    sent_at = request.session.get('otp_sent_at', 0)
    return (
        request.session.get('otp_user_id') == user.pk
        and bool(request.session.get('otp_code_hash'))
        and request.session.get('otp_expires_at', 0) > now
        and now - sent_at < settings.EMAIL_OTP_RESEND_SECONDS
    )


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
            messages.success(request, 'Inicio de sesión confirmado.')
            return redirect(next_url)

        remaining = settings.EMAIL_OTP_MAX_ATTEMPTS - attempts
        error = f'El código no es válido. Te quedan {remaining} intentos.'

    return render(request, 'tienda/verificar_2fa.html', {
        'email_oculto': _masked_email(user.email),
        'error': error,
    })


def registro(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    form = RegistroForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                usuario = form.save(commit=False)
                usuario.is_active = False
                usuario.save()
                Perfil.objects.create(
                    usuario=usuario,
                    rol='operador',
                    fecha_nacimiento=form.cleaned_data['fecha_nacimiento'],
                    terminos_aceptados_en=timezone.now(),
                    terminos_version=TERMS_VERSION,
                )
                _clear_pending_registration_otp(request)
                _issue_registration_code(request, usuario)
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

    items = []
    total = 0
    for key, item in carrito.items():
        subtotal = item['producto_precio'] * item['cantidad']
        total += subtotal
        items.append({**item, 'subtotal': subtotal, 'key': key})

    return render(request, 'tienda/pago.html', {'items': items, 'total': total})


@login_required
def procesar_pago(request):
    if es_admin(request.user):
        return redirect('historial_ventas')
    if request.method != 'POST':
        return redirect('ver_carrito')

    carrito = request.session.get('carrito', {})
    if not carrito:
        return redirect('lista_productos')

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
    venta = Venta.objects.filter(codigo=codigo).select_related('usuario').first()
    detalles = venta.detalles.select_related('producto').all() if venta else []
    return render(request, 'tienda/compra_exitosa.html', {
        'venta': venta,
        'detalles': detalles,
        'comprobante_enviado': request.session.pop('comprobante_enviado', None),
    })


# ─── MIS COMPRAS ──────────────────────────────────────────
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
