from django.contrib import admin
from .models import (
    CredencialFacial, CredencialPasskey, DetalleVenta, PagoSandbox,
    Perfil, Producto, SolicitudDevolucion, Venta,
)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'categoria', 'precio', 'stock', 'activo']
    list_filter = ['categoria', 'activo']
    search_fields = ['nombre', 'descripcion']
    list_editable = ['stock', 'activo']


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = [
        'codigo', 'usuario', 'fecha_venta', 'total', 'metodo_pago',
        'estado_pago', 'estado_envio', 'tipo_entrega',
    ]
    list_filter = ['metodo_pago', 'estado_pago', 'estado_envio', 'tipo_entrega', 'fecha_venta']
    search_fields = ['codigo', 'usuario__username', 'tracking', 'direccion_entrega']


@admin.register(DetalleVenta)
class DetalleVentaAdmin(admin.ModelAdmin):
    list_display = ['venta', 'producto', 'cantidad', 'precio_unitario', 'subtotal']


@admin.register(PagoSandbox)
class PagoSandboxAdmin(admin.ModelAdmin):
    list_display = [
        'venta', 'proveedor', 'estado', 'marca_tarjeta', 'ultimos_cuatro',
        'creado_en', 'aprobado_en',
    ]
    list_filter = ['proveedor', 'estado', 'marca_tarjeta']
    search_fields = ['venta__codigo', 'venta__usuario__username', 'referencia']
    readonly_fields = [
        'referencia', 'marca_tarjeta', 'ultimos_cuatro', 'motivo',
        'preferencia_externa', 'pago_externo_id', 'checkout_url',
        'stock_liberado', 'comprobante_enviado_en', 'aprobado_en',
        'creado_en', 'actualizado_en',
    ]


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = [
        'usuario', 'rol', 'verificacion_dos_pasos', 'fecha_nacimiento',
        'responsable_nombre', 'responsable_dni', 'terminos_version',
        'terminos_aceptados_en', 'registro_verificado_en',
    ]
    list_filter = ['rol', 'verificacion_dos_pasos']


@admin.register(SolicitudDevolucion)
class SolicitudDevolucionAdmin(admin.ModelAdmin):
    list_display = ['venta', 'motivo', 'estado', 'creada_en', 'resuelta_en']
    list_filter = ['motivo', 'estado', 'creada_en']
    search_fields = ['venta__codigo', 'venta__usuario__username', 'detalle']


@admin.register(CredencialPasskey)
class CredencialPasskeyAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'nombre', 'device_type', 'backed_up', 'creada_en', 'ultimo_uso']
    search_fields = ['usuario__username', 'usuario__email', 'nombre']
    readonly_fields = ['credential_id', 'public_key', 'sign_count', 'creada_en', 'ultimo_uso']


@admin.register(CredencialFacial)
class CredencialFacialAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'modelo', 'consentimiento_en', 'actualizada_en', 'ultimo_uso']
    search_fields = ['usuario__username', 'usuario__email']
    readonly_fields = [
        'descriptor', 'modelo', 'consentimiento_en', 'creada_en',
        'actualizada_en', 'ultimo_uso',
    ]
