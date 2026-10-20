from django.contrib import admin
from .models import CredencialFacial, CredencialPasskey, Producto, Venta, DetalleVenta, Perfil


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'categoria', 'precio', 'stock', 'activo']
    list_filter = ['categoria', 'activo']
    search_fields = ['nombre', 'descripcion']
    list_editable = ['stock', 'activo']


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'usuario', 'fecha_venta', 'total', 'metodo_pago', 'estado']
    list_filter = ['metodo_pago', 'estado', 'fecha_venta']
    search_fields = ['codigo', 'usuario__username']


@admin.register(DetalleVenta)
class DetalleVentaAdmin(admin.ModelAdmin):
    list_display = ['venta', 'producto', 'cantidad', 'precio_unitario', 'subtotal']


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = [
        'usuario', 'rol', 'fecha_nacimiento', 'terminos_version',
        'terminos_aceptados_en', 'registro_verificado_en',
    ]
    list_filter = ['rol']


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
