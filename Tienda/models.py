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
    terminos_aceptados_en = models.DateTimeField(null=True, blank=True)
    terminos_version = models.CharField(max_length=20, blank=True)
    registro_verificado_en = models.DateTimeField(null=True, blank=True)

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
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
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
    METODO_PAGO_CHOICES = [
        ('tarjeta', 'Tarjeta de Crédito'),
        ('debito', 'Tarjeta de Débito'),
        ('transferencia', 'Transferencia Bancaria'),
    ]
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('completada', 'Completada'),
        ('cancelada', 'Cancelada'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ventas')
    fecha_venta = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    metodo_pago = models.CharField(max_length=15, choices=METODO_PAGO_CHOICES)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='completada')
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
