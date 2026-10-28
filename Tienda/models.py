from django.db import models
from django.contrib.auth.models import User
import uuid


class Perfil(models.Model):
    ROL_CHOICES = [
        ('admin', 'Administrador'),
        ('operador', 'Operador'),
    ]

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    rol = models.CharField(max_length=10, choices=ROL_CHOICES, default='operador')
    fecha_nacimiento = models.DateField(null=True, blank=True)
    responsable_nombre = models.CharField(max_length=120, blank=True)
    responsable_dni = models.CharField(max_length=12, blank=True)
    responsable_parentesco = models.CharField(max_length=40, blank=True)
    terminos_aceptados_en = models.DateTimeField(null=True, blank=True)
    terminos_version = models.CharField(max_length=20, blank=True)
    registro_verificado_en = models.DateTimeField(null=True, blank=True)
    verificacion_dos_pasos = models.BooleanField(
        default=False,
        verbose_name='Verificación en dos pasos por email',
        help_text=(
            'Si está activa, se solicita un código por email al iniciar sesión '
            'y una confirmación de identidad antes de comprar.'
        ),
    )

    def __str__(self):
        return f"{self.usuario.username} - {self.get_rol_display()}"

    class Meta:
        verbose_name_plural = "Perfiles"


class CredencialPasskey(models.Model):
    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='credenciales_passkey',
    )
    nombre = models.CharField(max_length=80, default='Este dispositivo')
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.PositiveBigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    device_type = models.CharField(max_length=30, blank=True)
    backed_up = models.BooleanField(default=False)
    creada_en = models.DateTimeField(auto_now_add=True)
    ultimo_uso = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.usuario.username} - {self.nombre}'

    class Meta:
        verbose_name = 'Credencial Face ID / passkey'
        verbose_name_plural = 'Credenciales Face ID / passkey'
        ordering = ['-creada_en']


class CredencialFacial(models.Model):
    usuario = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='credencial_facial',
    )
    descriptor = models.JSONField()
    modelo = models.CharField(max_length=80, default='vladmandic-face-api-1.7.15')
    consentimiento_en = models.DateTimeField()
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    ultimo_uso = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.usuario.username} - reconocimiento facial'

    class Meta:
        verbose_name = 'Credencial facial'
        verbose_name_plural = 'Credenciales faciales'


class Producto(models.Model):
    CATEGORIA_CHOICES = [
        ('informatica', 'Informática'),
        ('componente_pc', 'Componente PC'),
        ('perifericos_gaming', 'Periféricos y Gaming'),
        ('redes_conectividad', 'Redes y Conectividad'),
        ('celulares_accesorios', 'Celulares y Accesorios'),
        ('cables_adaptadores', 'Cables y Adaptadores'),
        ('electronica_desarrollo', 'Electrónica y Desarrollo'),
        ('seguridad_domotica', 'Seguridad y Domótica'),
        ('lectores_tarjetas', 'Lectores de Tarjetas'),
        ('otros', 'Otros'),
    ]

    nombre = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, blank=True, default='', db_index=True)
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    costo = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    categoria = models.CharField(max_length=30, choices=CATEGORIA_CHOICES, default='otros')
    imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    peso_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                  help_text="Peso en kilogramos")
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

    class Meta:
        ordering = ['-fecha_creacion']


class Venta(models.Model):
    # Se mantienen los métodos históricos para visualizar ventas antiguas.
    # Las compras nuevas solo se crean con Mercado Pago.
    METODO_PAGO_CHOICES = [
        ('mercadopago', 'Mercado Pago'),
        ('tarjeta', 'Tarjeta de Crédito'),
        ('debito', 'Tarjeta de Débito'),
        ('transferencia', 'Transferencia Bancaria'),
    ]
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('completada', 'Completada'),
        ('cancelada', 'Cancelada'),
    ]
    ESTADO_PAGO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('procesando', 'Procesando'),
        ('pagado', 'Pagado'),
        ('rechazado', 'Rechazado'),
        ('reembolsado', 'Reembolsado'),
    ]
    ESTADO_ENVIO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('preparando', 'Preparando'),
        ('enviado', 'Enviado'),
        ('entregado', 'Entregado'),
        ('cancelado', 'Cancelado'),
    ]
    TIPO_ENTREGA_CHOICES = [
        ('envio', 'Envío a domicilio'),
        ('retiro', 'Retiro en tienda'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ventas')
    fecha_venta = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    metodo_pago = models.CharField(max_length=15, choices=METODO_PAGO_CHOICES)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='completada')
    estado_pago = models.CharField(max_length=12, choices=ESTADO_PAGO_CHOICES, default='pagado')
    estado_envio = models.CharField(max_length=12, choices=ESTADO_ENVIO_CHOICES, default='preparando')
    tipo_entrega = models.CharField(max_length=10, choices=TIPO_ENTREGA_CHOICES, default='retiro')
    direccion_entrega = models.CharField(max_length=250, blank=True)
    entrega_localidad = models.CharField(max_length=100, blank=True)
    entrega_provincia = models.CharField(max_length=100, blank=True)
    entrega_codigo_postal = models.CharField(max_length=12, blank=True)
    entrega_latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    entrega_longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    transportista = models.CharField(max_length=80, blank=True)
    tracking = models.CharField(max_length=80, blank=True)
    codigo = models.CharField(max_length=20, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = f"GS-{str(uuid.uuid4())[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} - {self.usuario.username}"

    class Meta:
        ordering = ['-fecha_venta']


class DetalleVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='detalles_venta')
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        self.subtotal = self.precio_unitario * self.cantidad
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.producto.nombre} x{self.cantidad}"

    class Meta:
        verbose_name_plural = "Detalles de venta"


class PagoSandbox(models.Model):
    """Registro interno del pago, sin almacenar datos sensibles de la tarjeta."""

    # Los valores históricos se conservan para que las ventas antiguas sigan
    # mostrando su método; las compras nuevas solo usan Mercado Pago.
    PROVEEDOR_CHOICES = [
        ('mercadopago', 'Mercado Pago'),
        ('demopay', 'DemoPay Sandbox'),
        ('transferencia', 'Transferencia bancaria'),
    ]
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('procesando', 'Procesando'),
        ('aprobado', 'Aprobado'),
        ('rechazado', 'Rechazado'),
        ('reembolsado', 'Reembolsado'),
    ]

    venta = models.OneToOneField(
        Venta,
        on_delete=models.CASCADE,
        related_name='pago_sandbox',
    )
    referencia = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    proveedor = models.CharField(max_length=20, choices=PROVEEDOR_CHOICES)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='pendiente')
    marca_tarjeta = models.CharField(max_length=20, blank=True)
    ultimos_cuatro = models.CharField(max_length=4, blank=True)
    motivo = models.CharField(max_length=120, blank=True)
    preferencia_externa = models.CharField(max_length=120, blank=True)
    pago_externo_id = models.CharField(max_length=120, blank=True, db_index=True)
    checkout_url = models.URLField(max_length=500, blank=True)
    stock_liberado = models.BooleanField(default=False)
    comprobante_enviado_en = models.DateTimeField(null=True, blank=True)
    aprobado_en = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.venta.codigo} - {self.get_estado_display()}'

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'


class SolicitudDevolucion(models.Model):
    """Solicitud trazable de devolución asociada a una compra."""

    MOTIVO_CHOICES = [
        ('arrepentimiento', 'Me arrepentí de la compra'),
        ('defectuoso', 'El producto llegó defectuoso'),
        ('incorrecto', 'Recibí un producto incorrecto'),
        ('danado', 'El pedido llegó dañado'),
        ('otro', 'Otro motivo'),
    ]
    ESTADO_CHOICES = [
        ('solicitada', 'Solicitada'),
        ('aprobada', 'Aprobada'),
        ('rechazada', 'Rechazada'),
    ]

    venta = models.OneToOneField(
        Venta,
        on_delete=models.CASCADE,
        related_name='devolucion',
    )
    motivo = models.CharField(max_length=20, choices=MOTIVO_CHOICES)
    detalle = models.TextField(blank=True, max_length=600)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='solicitada')
    respuesta = models.CharField(max_length=300, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    resuelta_en = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.venta.codigo} - {self.get_estado_display()}'

    class Meta:
        ordering = ['-creada_en']
        verbose_name = 'Solicitud de devolución'
        verbose_name_plural = 'Solicitudes de devolución'
