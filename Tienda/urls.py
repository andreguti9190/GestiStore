from django.urls import path
from . import views

urlpatterns = [
    # Inicio
    path('', views.inicio, name='inicio'),

    # Auth
    path('registro/', views.registro, name='registro'),
    path('registro/verificar/', views.verificar_registro, name='verificar_registro'),
    path('terminos-y-condiciones/', views.terminos_y_condiciones, name='terminos_y_condiciones'),

    # Productos
    path('productos/', views.lista_productos, name='lista_productos'),
    path('productos/<int:pk>/', views.detalle_producto, name='detalle_producto'),
    path('productos/nuevo/', views.crear_producto, name='crear_producto'),
    path('productos/<int:pk>/editar/', views.editar_producto, name='editar_producto'),
    path('productos/<int:pk>/eliminar/', views.eliminar_producto, name='eliminar_producto'),

    # Carrito
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('carrito/agregar/<int:pk>/', views.agregar_carrito, name='agregar_carrito'),
    path('carrito/eliminar/<str:key>/', views.eliminar_carrito, name='eliminar_carrito'),
    path('carrito/confirmar/', views.confirmar_compra, name='confirmar_compra'),
    path('carrito/procesar/', views.procesar_pago, name='procesar_pago'),
    path('carrito/exitoso/', views.compra_exitosa, name='compra_exitosa'),

    # Mis compras
    path('mis-compras/', views.mis_compras, name='mis_compras'),

    # Historial de ventas (admin)
    path('ventas/', views.historial_ventas, name='historial_ventas'),
]
