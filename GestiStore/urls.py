from django.contrib import admin
from django.urls import path, include, re_path
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as serve_media
from django.urls import reverse_lazy
from Tienda import views

urlpatterns = [
    path('admin/', admin.site.urls),

    path('login/', views.iniciar_sesion, name='login'),
    path('login/verificar/', views.verificar_2fa, name='verificar_2fa'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('recuperar-contrasena/', views.PasswordResetConBaseView.as_view(
        template_name='tienda/password_reset_form.html',
        email_template_name='tienda/emails/password_reset_email.txt',
        html_email_template_name='tienda/emails/password_reset_email.html',
        subject_template_name='tienda/emails/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done'),
    ), name='password_reset'),
    path('recuperar-contrasena/enviado/', auth_views.PasswordResetDoneView.as_view(
        template_name='tienda/password_reset_done.html',
    ), name='password_reset_done'),
    path('recuperar-contrasena/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='tienda/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    ), name='password_reset_confirm'),
    path('recuperar-contrasena/completado/', auth_views.PasswordResetCompleteView.as_view(
        template_name='tienda/password_reset_complete.html',
    ), name='password_reset_complete'),

    path('', include('Tienda.urls')),
]

handler403 = views.error_403

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_MEDIA_FILES:
    # El iniciador de demo usa DEBUG=False y no tiene un servidor de media externo.
    # static() omite las rutas con DEBUG=False; registramos solo MEDIA_ROOT.
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve_media, {
            'document_root': settings.MEDIA_ROOT,
            'show_indexes': False,
        }),
    ]
