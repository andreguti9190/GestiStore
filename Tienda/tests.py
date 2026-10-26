import re
import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from cryptography import x509
from webauthn.helpers import bytes_to_base64url

from scripts.generar_certificado_https import generate_certificate
from scripts.iniciar_facil import _tunnel_url
from .models import (
    CredencialFacial, CredencialPasskey, DetalleVenta, PagoSandbox,
    Perfil, Producto, SolicitudDevolucion, Venta,
)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RecuperarContrasenaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='recuperable',
            email='recuperable@example.com',
            password='ClaveAnterior123!',
        )

    def test_solicitud_envia_enlace_y_permite_cambiar_contrasena(self):
        response = self.client.post(reverse('password_reset'), {
            'email': 'RECUPERABLE@example.com',
        })

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn('Tu nombre de usuario es: recuperable', mail.outbox[0].body)

        enlace = re.search(r'https?://[^\s]+', mail.outbox[0].body).group()
        confirmacion = self.client.get(urlparse(enlace).path)
        self.assertEqual(confirmacion.status_code, 302)

        response = self.client.post(confirmacion.url, {
            'new_password1': 'ClaveNuevaSegura456!',
            'new_password2': 'ClaveNuevaSegura456!',
        })

        self.assertRedirects(response, reverse('password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ClaveNuevaSegura456!'))
        self.assertFalse(self.user.check_password('ClaveAnterior123!'))

    def test_email_desconocido_no_revela_si_existe(self):
        response = self.client.post(reverse('password_reset'), {
            'email': 'nadie@example.com',
        })

        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(PUBLIC_BASE_URL='http://10.20.30.40:9000')
    def test_enlace_usa_la_ip_configurada_al_iniciar_servidor(self):
        self.client.post(reverse('password_reset'), {
            'email': self.user.email,
        }, HTTP_HOST='localhost:8000')

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            'http://10.20.30.40:9000/recuperar-contrasena/',
            mail.outbox[0].body,
        )


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class LoginDosFactoresTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='cliente',
            email='cliente@example.com',
            password='UnaClaveSegura123!',
        )

    def iniciar_primer_factor(self):
        return self.client.post(reverse('login'), {
            'username': self.user.username,
            'password': 'UnaClaveSegura123!',
        })

    def test_password_correcta_envia_codigo_y_no_inicia_sesion(self):
        response = self.iniciar_primer_factor()

        self.assertRedirects(response, reverse('verificar_2fa'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertIn('otp_code_hash', self.client.session)

    def test_formulario_repetido_no_envia_otro_codigo(self):
        primera_respuesta = self.iniciar_primer_factor()
        segunda_respuesta = self.iniciar_primer_factor()

        self.assertRedirects(primera_respuesta, reverse('verificar_2fa'))
        self.assertRedirects(segunda_respuesta, reverse('verificar_2fa'))
        self.assertEqual(len(mail.outbox), 1)

    def test_codigo_correcto_completa_login(self):
        self.iniciar_primer_factor()
        codigo = re.search(r'\b\d{6}\b', mail.outbox[0].body).group()

        response = self.client.post(reverse('verificar_2fa'), {'codigo': codigo})

        self.assertRedirects(response, reverse('inicio'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        self.assertNotIn('otp_code_hash', self.client.session)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('Nuevo inicio de sesión', mail.outbox[-1].subject)
        self.assertEqual(mail.outbox[-1].to, [self.user.email])

    @override_settings(
        ALLOWED_HOSTS=['demo-store.trycloudflare.com'],
        CSRF_TRUSTED_ORIGINS=['https://demo-store.trycloudflare.com'],
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
        SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
    )
    def test_login_conserva_sesion_detras_del_tunel_https(self):
        tunnel = {
            'HTTP_HOST': 'demo-store.trycloudflare.com',
            'HTTP_X_FORWARDED_PROTO': 'https',
        }
        response = self.client.post(reverse('login'), {
            'username': self.user.username,
            'password': 'UnaClaveSegura123!',
        }, **tunnel)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('verificar_2fa'))
        self.assertTrue(response.cookies['sessionid']['secure'])
        codigo = re.search(r'\b\d{6}\b', mail.outbox[0].body).group()

        response = self.client.post(
            reverse('verificar_2fa'), {'codigo': codigo}, **tunnel
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('inicio'))
        self.assertTrue(response.cookies['sessionid']['secure'])
        response = self.client.get(reverse('inicio'), **tunnel)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_smtp_de_aviso_no_bloquea_la_respuesta_de_login(self):
        self.iniciar_primer_factor()
        codigo = re.search(r'\b\d{6}\b', mail.outbox[0].body).group()

        with override_settings(
            EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend'
        ), patch('Tienda.views.threading.Thread') as thread:
            response = self.client.post(
                reverse('verificar_2fa'), {'codigo': codigo}
            )

        self.assertRedirects(response, reverse('inicio'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        thread.assert_called_once()
        thread.return_value.start.assert_called_once_with()

    def test_codigo_incorrecto_no_inicia_sesion(self):
        self.iniciar_primer_factor()

        response = self.client.post(reverse('verificar_2fa'), {'codigo': '000000'})

        self.assertContains(response, 'El código no es válido')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_codigo_vencido_obliga_a_reiniciar(self):
        self.iniciar_primer_factor()
        session = self.client.session
        session['otp_expires_at'] = int(timezone.now().timestamp()) - 1
        session.save()

        response = self.client.get(reverse('verificar_2fa'))

        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('otp_code_hash', self.client.session)

    def test_usuario_sin_email_no_puede_iniciar_segundo_factor(self):
        self.user.email = ''
        self.user.save(update_fields=['email'])

        response = self.iniciar_primer_factor()

        self.assertContains(response, 'no tiene un email registrado')
        self.assertEqual(len(mail.outbox), 0)

    def test_formulario_de_login_no_se_guarda_en_cache(self):
        response = self.client.get(reverse('login'))

        self.assertIn('no-cache', response.headers['Cache-Control'])

    def test_encabezado_de_login_muestra_solamente_la_marca(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, 'class="header-brand"')
        self.assertNotContains(response, 'class="nav-links"')
        self.assertNotContains(response, 'class="header-right"')
        self.assertNotContains(response, 'id="mobile-menu"')

    def test_registro_y_recuperacion_tambien_muestran_solamente_la_marca(self):
        for url_name in ('registro', 'password_reset'):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertContains(response, 'class="header-brand"')
                self.assertNotContains(response, 'class="nav-links"')
                self.assertNotContains(response, 'class="header-right"')
                self.assertNotContains(response, 'id="mobile-menu"')

    def test_token_csrf_vencido_recupera_la_pantalla_de_codigo(self):
        client = Client(enforce_csrf_checks=True)
        session = client.session
        session['otp_user_id'] = self.user.pk
        session['otp_code_hash'] = 'hash-pendiente'
        session['otp_expires_at'] = int(timezone.now().timestamp()) + 600
        session.save()

        page = client.get(reverse('verificar_2fa'))
        old_token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"',
            page.content.decode(),
        ).group(1)
        client.cookies['csrftoken'] = 'a' * 32

        response = client.post(
            reverse('verificar_2fa'),
            {'csrfmiddlewaretoken': old_token, 'codigo': '123456'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], reverse('verificar_2fa'))
        self.assertContains(response, 'La página de seguridad había vencido')

    def test_csrf_vencido_en_login_facial_devuelve_error_claro(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            reverse('login_facial'),
            data='{}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn('sesión de seguridad venció', response.json()['error'])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RegistroDosFactoresTests(TestCase):
    def datos_validos(self, **cambios):
        datos = {
            'username': 'cliente_nuevo',
            'email': 'nuevo@example.com',
            'fecha_nacimiento': (timezone.localdate() - timedelta(days=365 * 25)).isoformat(),
            'password1': 'UnaClaveSegura123!',
            'password2': 'UnaClaveSegura123!',
            'acepta_terminos': 'on',
        }
        datos.update(cambios)
        return datos

    def test_registro_crea_cuenta_inactiva_y_envia_codigo(self):
        response = self.client.post(reverse('registro'), self.datos_validos())

        self.assertRedirects(response, reverse('verificar_registro'))
        usuario = User.objects.get(username='cliente_nuevo')
        self.assertFalse(usuario.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['nuevo@example.com'])
        self.assertIn('registration_otp_code_hash', self.client.session)
        self.assertEqual(usuario.perfil.terminos_version, '2026-10-19')
        self.assertIsNotNone(usuario.perfil.terminos_aceptados_en)

    def test_codigo_correcto_activa_cuenta_e_inicia_sesion(self):
        self.client.post(reverse('registro'), self.datos_validos())
        codigo = re.search(r'\b\d{6}\b', mail.outbox[0].body).group()

        response = self.client.post(reverse('verificar_registro'), {'codigo': codigo})

        self.assertRedirects(response, reverse('inicio'))
        usuario = User.objects.get(username='cliente_nuevo')
        self.assertTrue(usuario.is_active)
        self.assertEqual(int(self.client.session['_auth_user_id']), usuario.pk)
        self.assertIsNotNone(usuario.perfil.registro_verificado_en)
        self.assertNotIn('registration_otp_code_hash', self.client.session)

    def test_menor_de_18_necesita_adulto_responsable(self):
        fecha_menor = timezone.localdate().replace(year=timezone.localdate().year - 17)

        response = self.client.post(
            reverse('registro'),
            self.datos_validos(fecha_nacimiento=fecha_menor.isoformat()),
        )

        self.assertContains(response, 'Ingresá el nombre del adulto responsable')
        self.assertFalse(User.objects.filter(username='cliente_nuevo').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_menor_con_responsable_puede_iniciar_registro(self):
        fecha_menor = timezone.localdate().replace(year=timezone.localdate().year - 16)

        response = self.client.post(reverse('registro'), self.datos_validos(
            fecha_nacimiento=fecha_menor.isoformat(),
            responsable_nombre='María Responsable',
            responsable_dni='30123456',
            responsable_parentesco='Madre',
            autorizacion_responsable='on',
        ))

        self.assertRedirects(response, reverse('verificar_registro'))
        perfil = User.objects.get(username='cliente_nuevo').perfil
        self.assertEqual(perfil.responsable_nombre, 'María Responsable')
        self.assertEqual(perfil.responsable_dni, '30123456')
        self.assertEqual(perfil.responsable_parentesco, 'Madre')

    def test_sin_aceptar_terminos_no_puede_registrarse(self):
        datos = self.datos_validos()
        datos.pop('acepta_terminos')

        response = self.client.post(reverse('registro'), datos)

        self.assertContains(response, 'Tenés que aceptar los Términos y Condiciones')
        self.assertFalse(User.objects.filter(username='cliente_nuevo').exists())

    @patch('Tienda.views.send_registration_code', side_effect=Exception('SMTP caído'))
    def test_falla_de_email_no_deja_cuenta_inactiva_bloqueando_datos(self, _send):
        response = self.client.post(reverse('registro'), self.datos_validos())

        self.assertContains(response, 'No pudimos enviar el código de verificación')
        self.assertFalse(User.objects.filter(username='cliente_nuevo').exists())
        self.assertFalse(Perfil.objects.filter(usuario__email='nuevo@example.com').exists())

    @patch('Tienda.views.User.save', side_effect=IntegrityError('usuario duplicado'))
    def test_colision_de_usuario_muestra_error_claro(self, _save):
        response = self.client.post(reverse('registro'), self.datos_validos())

        self.assertContains(response, 'Ese nombre de usuario acaba de registrarse')
        self.assertNotContains(response, 'No pudimos enviar el código de verificación')

    def test_registro_bloquea_envios_repetidos_en_el_navegador(self):
        response = self.client.get(reverse('registro'))

        self.assertContains(response, 'id="registration-form"')
        self.assertContains(response, "button.disabled = true")

    def test_registro_incompleto_se_puede_reiniciar_con_los_mismos_datos(self):
        usuario_anterior = User.objects.create_user(
            username='cliente_nuevo',
            email='nuevo@example.com',
            password='ClaveAnterior123!',
            is_active=False,
        )
        Perfil.objects.create(usuario=usuario_anterior, registro_verificado_en=None)
        pk_anterior = usuario_anterior.pk

        response = self.client.post(reverse('registro'), self.datos_validos())

        self.assertRedirects(response, reverse('verificar_registro'))
        usuario_nuevo = User.objects.get(username='cliente_nuevo')
        self.assertEqual(usuario_nuevo.pk, pk_anterior)
        self.assertFalse(usuario_nuevo.is_active)
        self.assertTrue(usuario_nuevo.check_password('UnaClaveSegura123!'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('registration_otp_code_hash', self.client.session)

    def test_terminos_son_publicos(self):
        response = self.client.get(reverse('terminos_y_condiciones'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Términos y Condiciones')
        self.assertContains(response, 'Ley 25.326')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasskeyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='passkey_user',
            email='passkey@example.com',
            password='UnaClaveSegura123!',
        )
        Perfil.objects.create(usuario=self.user)

    def test_seguridad_y_opciones_de_registro_requieren_sesion(self):
        response = self.client.get(reverse('seguridad_cuenta'))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user)
        response = self.client.get(reverse('seguridad_cuenta'))
        self.assertContains(response, 'Reconocimiento facial')

        response = self.client.post(
            reverse('passkey_registro_opciones'),
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('challenge', response.json())
        self.assertIsNone(
            response.json()['authenticatorSelection'].get('authenticatorAttachment')
        )
        self.assertIn('passkey_registration_challenge', self.client.session)

    @patch('Tienda.views.verify_registration_response')
    def test_registra_una_passkey_para_el_usuario_actual(self, verify):
        verify.return_value = SimpleNamespace(
            credential_id=b'credential-id',
            credential_public_key=b'public-key',
            sign_count=0,
            credential_device_type=SimpleNamespace(value='single_device'),
            credential_backed_up=False,
        )
        self.client.force_login(self.user)
        self.client.post(
            reverse('passkey_registro_opciones'),
            data='{}',
            content_type='application/json',
        )

        response = self.client.post(
            reverse('passkey_registro_verificar'),
            data=json.dumps({
                'name': 'iPhone personal',
                'credential': {
                    'id': bytes_to_base64url(b'credential-id'),
                    'response': {'transports': ['internal']},
                },
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        saved = CredencialPasskey.objects.get(usuario=self.user)
        self.assertEqual(saved.nombre, 'iPhone personal')
        self.assertEqual(bytes(saved.public_key), b'public-key')
        self.assertEqual(saved.transports, ['internal'])

    @patch('Tienda.views.verify_authentication_response')
    def test_passkey_registrada_permite_iniciar_sesion(self, verify):
        saved = CredencialPasskey.objects.create(
            usuario=self.user,
            nombre='iPhone',
            credential_id=b'credential-id',
            public_key=b'public-key',
        )
        verify.return_value = SimpleNamespace(
            new_sign_count=1,
            credential_device_type=SimpleNamespace(value='multi_device'),
            credential_backed_up=True,
        )
        response = self.client.post(
            reverse('passkey_login_opciones'),
            data=json.dumps({'next': reverse('lista_productos')}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse('passkey_login_verificar'),
            data=json.dumps({
                'credential': {'id': bytes_to_base64url(b'credential-id')},
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect'], reverse('lista_productos'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        saved.refresh_from_db()
        self.assertEqual(saved.sign_count, 1)
        self.assertIsNotNone(saved.ultimo_uso)

    def test_usuario_puede_eliminar_su_passkey(self):
        saved = CredencialPasskey.objects.create(
            usuario=self.user,
            credential_id=b'credential-id',
            public_key=b'public-key',
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse('eliminar_passkey', args=[saved.pk]))

        self.assertRedirects(response, reverse('seguridad_cuenta'))
        self.assertFalse(CredencialPasskey.objects.filter(pk=saved.pk).exists())


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ReconocimientoFacialTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='rostro_user',
            email='rostro@example.com',
            password='UnaClaveSegura123!',
        )
        Perfil.objects.create(usuario=self.user)
        self.descriptor = [1.0] + [0.0] * 127
        self.capturas = [self.descriptor, self.descriptor, self.descriptor]

    def test_registro_requiere_sesion_y_consentimiento(self):
        response = self.client.post(
            reverse('registrar_rostro'),
            data=json.dumps({'descriptors': self.capturas, 'consent': True}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('registrar_rostro'),
            data=json.dumps({'descriptors': self.capturas, 'consent': False}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CredencialFacial.objects.filter(usuario=self.user).exists())

    def test_registra_descriptor_sin_guardar_imagen(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('registrar_rostro'),
            data=json.dumps({'descriptors': self.capturas, 'consent': True}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        saved = CredencialFacial.objects.get(usuario=self.user)
        self.assertEqual(len(saved.descriptor), 128)
        self.assertAlmostEqual(saved.descriptor[0], 1.0)
        self.assertEqual(saved.modelo, settings.FACE_RECOGNITION_MODEL_VERSION)
        self.assertIsNotNone(saved.consentimiento_en)

    def test_no_registra_capturas_de_personas_distintas(self):
        distinto = [0.0, 1.0] + [0.0] * 126
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('registrar_rostro'),
            data=json.dumps({
                'descriptors': [self.descriptor, self.descriptor, distinto],
                'consent': True,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('capturas no fueron consistentes', response.json()['error'])
        self.assertFalse(CredencialFacial.objects.filter(usuario=self.user).exists())

    def test_rostro_coincidente_inicia_sesion(self):
        CredencialFacial.objects.create(
            usuario=self.user,
            descriptor=self.descriptor,
            modelo=settings.FACE_RECOGNITION_MODEL_VERSION,
            consentimiento_en=timezone.now(),
        )

        response = self.client.post(
            reverse('login_facial'),
            data=json.dumps({
                'username': self.user.username,
                'descriptors': self.capturas,
                'next': reverse('lista_productos'),
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['redirect'], reverse('lista_productos'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_rostro_distinto_no_inicia_sesion(self):
        CredencialFacial.objects.create(
            usuario=self.user,
            descriptor=self.descriptor,
            modelo=settings.FACE_RECOGNITION_MODEL_VERSION,
            consentimiento_en=timezone.now(),
        )
        distinto = [0.0, 1.0] + [0.0] * 126

        response = self.client.post(
            reverse('login_facial'),
            data=json.dumps({
                'username': self.user.username,
                'descriptors': [distinto, distinto, distinto],
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_rostro_cercano_pero_distinto_no_inicia_sesion(self):
        CredencialFacial.objects.create(
            usuario=self.user,
            descriptor=self.descriptor,
            modelo=settings.FACE_RECOGNITION_MODEL_VERSION,
            consentimiento_en=timezone.now(),
        )
        # La distancia es 0,5: antes quedaba debajo del umbral permisivo 0,55.
        distinto = [0.875, 0.484122918] + [0.0] * 126

        response = self.client.post(
            reverse('login_facial'),
            data=json.dumps({
                'username': self.user.username,
                'descriptors': [distinto, distinto, distinto],
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_registro_facial_anterior_exige_actualizacion(self):
        CredencialFacial.objects.create(
            usuario=self.user,
            descriptor=self.descriptor,
            modelo='vladmandic-face-api-1.7.15',
            consentimiento_en=timezone.now(),
        )

        response = self.client.post(
            reverse('login_facial'),
            data=json.dumps({
                'username': self.user.username,
                'descriptors': self.capturas,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('actualizar tu rostro', response.json()['error'])
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_sesion_abierta_no_simula_otro_ingreso_facial(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('login_facial'),
            data=json.dumps({
                'username': self.user.username,
                'descriptors': self.capturas,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Ya hay una sesión iniciada', response.json()['error'])

    def test_usuario_puede_eliminar_su_rostro(self):
        CredencialFacial.objects.create(
            usuario=self.user,
            descriptor=self.descriptor,
            modelo=settings.FACE_RECOGNITION_MODEL_VERSION,
            consentimiento_en=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse('eliminar_rostro'))

        self.assertRedirects(response, reverse('seguridad_cuenta'))
        self.assertFalse(CredencialFacial.objects.filter(usuario=self.user).exists())


class CertificadoHttpsTests(TestCase):
    def test_certificado_incluye_dominio_y_se_puede_descargar(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as temporary_dir:
            base_dir = Path(temporary_dir)
            certificate_dir = base_dir / '.certificados'
            paths = generate_certificate(
                '192.168.1.25',
                certificate_dir,
                '192-168-1-25.sslip.io',
            )
            server_certificate = x509.load_pem_x509_certificate(
                paths['server_certificate'].read_bytes()
            )
            ca_certificate = x509.load_der_x509_certificate(
                paths['ca_certificate'].read_bytes()
            )
            server_certificate.verify_directly_issued_by(ca_certificate)
            san = server_certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            self.assertIn(
                '192-168-1-25.sslip.io',
                san.get_values_for_type(x509.DNSName),
            )

            with override_settings(BASE_DIR=base_dir):
                response = self.client.get(reverse('descargar_certificado_local'))
                content = b''.join(response.streaming_content)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(content, paths['ca_certificate'].read_bytes())
            self.assertIn('amperestore-ca.cer', response['Content-Disposition'])


class InicioFacilTests(TestCase):
    def test_extrae_solamente_un_enlace_https_de_cloudflare(self):
        output = (
            'INF Your quick Tunnel has been created! '
            'https://ampere-demo.trycloudflare.com'
        )

        self.assertEqual(
            _tunnel_url(output),
            'https://ampere-demo.trycloudflare.com',
        )
        self.assertIsNone(_tunnel_url('https://sitio-no-autorizado.example'))

    def test_no_confunde_api_de_cloudflare_con_url_publica(self):
        output = (
            'Requesting new quick Tunnel on '
            'https://api.trycloudflare.com/tunnel'
        )

        self.assertIsNone(_tunnel_url(output))

    def test_ignora_api_y_conserva_url_publica_si_comparten_linea(self):
        output = (
            'https://api.trycloudflare.com '
            'https://bright-store-demo.trycloudflare.com'
        )

        self.assertEqual(
            _tunnel_url(output),
            'https://bright-store-demo.trycloudflare.com',
        )


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ComprobanteCompraTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='comprador',
            email='comprador@example.com',
            password='UnaClaveSegura123!',
        )
        self.producto = Producto.objects.create(
            nombre='Teclado',
            precio='12500.00',
            stock=5,
            categoria='perifericos_gaming',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['carrito'] = {
            str(self.producto.pk): {
                'producto_id': self.producto.pk,
                'producto_nombre': self.producto.nombre,
                'producto_precio': 12500.0,
                'producto_imagen': '',
                'producto_categoria': 'Periféricos y Gaming',
                'cantidad': 2,
            }
        }
        session.save()

    def test_transferencia_crea_pedido_pendiente_sin_comprobante(self):
        response = self.client.post(reverse('procesar_pago'), {
            'metodo_pago': 'transferencia',
            'verification_method': 'password',
            'account_password': 'UnaClaveSegura123!',
        })

        self.assertRedirects(response, reverse('compra_exitosa'))
        venta = Venta.objects.get(usuario=self.user)
        self.assertEqual(venta.total, 25000)
        self.assertEqual(DetalleVenta.objects.filter(venta=venta).count(), 1)
        self.assertEqual(venta.estado, 'pendiente')
        self.assertEqual(venta.estado_pago, 'pendiente')
        self.assertEqual(venta.pago_sandbox.proveedor, 'transferencia')
        self.assertEqual(len(mail.outbox), 0)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)

    def test_envio_guarda_direccion_y_coordenadas(self):
        self.client.post(reverse('procesar_pago'), {
            'metodo_pago': 'transferencia',
            'verification_method': 'password',
            'account_password': 'UnaClaveSegura123!',
            'tipo_entrega': 'envio',
            'direccion_entrega': 'Av. Corrientes 1234',
            'entrega_localidad': 'CABA',
            'entrega_provincia': 'Buenos Aires',
            'entrega_codigo_postal': 'C1043',
            'entrega_latitud': '-34.603700',
            'entrega_longitud': '-58.381600',
        })

        venta = Venta.objects.get(usuario=self.user)
        self.assertEqual(venta.tipo_entrega, 'envio')
        self.assertEqual(venta.direccion_entrega, 'Av. Corrientes 1234')
        self.assertEqual(str(venta.entrega_latitud), '-34.603700')

    def test_envio_requiere_ubicacion_en_mapa(self):
        response = self.client.post(reverse('procesar_pago'), {
            'metodo_pago': 'transferencia',
            'verification_method': 'password',
            'account_password': 'UnaClaveSegura123!',
            'tipo_entrega': 'envio',
            'direccion_entrega': 'Av. Corrientes 1234',
            'entrega_localidad': 'CABA',
            'entrega_provincia': 'Buenos Aires',
            'entrega_codigo_postal': 'C1043',
        }, follow=True)

        self.assertContains(response, 'Marcá en el mapa')
        self.assertFalse(Venta.objects.filter(usuario=self.user).exists())

    @patch('Tienda.views.send_purchase_receipt', side_effect=Exception('SMTP caído'))
    def test_falla_de_email_no_anula_la_compra(self, _send):
        response = self.client.post(reverse('procesar_pago'), {
            'metodo_pago': 'tarjeta',
            'verification_method': 'password',
            'account_password': 'UnaClaveSegura123!',
        })
        payment = PagoSandbox.objects.get(venta__usuario=self.user)
        response = self.client.post(
            reverse('pago_sandbox', args=[payment.referencia]),
            {'demo_token': 'demo_visa_approved'},
        )

        self.assertEqual(self.client.session['comprobante_enviado'], False)
        self.assertRedirects(response, reverse('compra_exitosa'))
        self.assertEqual(Venta.objects.filter(usuario=self.user).count(), 1)
        self.assertEqual(Venta.objects.get(usuario=self.user).estado_pago, 'pagado')

    @patch('Tienda.views.publish_dashboard_event')
    def test_compra_emite_evento_websocket_al_confirmarse(self, publish):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('procesar_pago'), {
                'metodo_pago': 'transferencia',
                'verification_method': 'password',
                'account_password': 'UnaClaveSegura123!',
            })

        self.assertRedirects(response, reverse('compra_exitosa'))
        venta = Venta.objects.get(usuario=self.user)
        publish.assert_called_once_with('sale.created', venta.pk)

    def iniciar_pago_tarjeta(self):
        response = self.client.post(reverse('procesar_pago'), {
            'metodo_pago': 'tarjeta',
            'verification_method': 'password',
            'account_password': 'UnaClaveSegura123!',
        })
        payment = PagoSandbox.objects.get(venta__usuario=self.user)
        self.assertRedirects(
            response,
            reverse('pago_sandbox', args=[payment.referencia]),
            fetch_redirect_response=False,
        )
        return payment

    def test_tarjeta_aprobada_detecta_marca_y_envia_comprobante(self):
        payment = self.iniciar_pago_tarjeta()

        response = self.client.post(
            reverse('pago_sandbox', args=[payment.referencia]),
            {'demo_token': 'demo_mastercard_approved'},
        )

        self.assertRedirects(response, reverse('compra_exitosa'))
        payment.refresh_from_db()
        payment.venta.refresh_from_db()
        self.assertEqual(payment.estado, 'aprobado')
        self.assertEqual(payment.marca_tarjeta, 'Mastercard')
        self.assertEqual(payment.ultimos_cuatro, '4444')
        self.assertEqual(payment.venta.estado_pago, 'pagado')
        self.assertEqual(payment.venta.estado, 'completada')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(payment.venta.codigo, mail.outbox[0].subject)

    def test_tarjeta_rechazada_libera_stock(self):
        payment = self.iniciar_pago_tarjeta()

        self.client.post(
            reverse('pago_sandbox', args=[payment.referencia]),
            {'demo_token': 'demo_mastercard_rejected'},
        )

        payment.refresh_from_db()
        payment.venta.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(payment.estado, 'rechazado')
        self.assertTrue(payment.stock_liberado)
        self.assertEqual(payment.venta.estado_pago, 'rechazado')
        self.assertEqual(payment.venta.estado, 'cancelada')
        self.assertEqual(self.producto.stock, 5)
        self.assertEqual(len(mail.outbox), 0)

    def test_tarjeta_pendiente_no_envia_comprobante(self):
        payment = self.iniciar_pago_tarjeta()

        self.client.post(
            reverse('pago_sandbox', args=[payment.referencia]),
            {'demo_token': 'demo_visa_pending'},
        )

        payment.refresh_from_db()
        payment.venta.refresh_from_db()
        self.assertEqual(payment.estado, 'pendiente')
        self.assertEqual(payment.venta.estado_pago, 'procesando')
        self.assertEqual(len(mail.outbox), 0)

    def test_sandbox_rechaza_tarjeta_que_no_es_de_prueba(self):
        payment = self.iniciar_pago_tarjeta()

        response = self.client.post(
            reverse('pago_sandbox', args=[payment.referencia]),
            {'demo_token': 'token_inventado'},
            follow=True,
        )

        self.assertContains(response, 'no pertenece al entorno de demostración')
        payment.refresh_from_db()
        self.assertEqual(payment.estado, 'pendiente')

    def test_pago_aprobado_repetido_no_duplica_el_comprobante(self):
        payment = self.iniciar_pago_tarjeta()
        url = reverse('pago_sandbox', args=[payment.referencia])

        self.client.post(url, {'demo_token': 'demo_visa_approved'})
        self.client.post(url, {'demo_token': 'demo_visa_approved'})

        self.assertEqual(len(mail.outbox), 1)


class DashboardVendedorTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='vendedor', email='vendedor@example.com', password='clave-segura'
        )
        Perfil.objects.create(usuario=self.admin, rol='admin')
        self.cliente = User.objects.create_user(
            username='cliente-dashboard', email='cliente@example.com', password='clave-segura'
        )
        Perfil.objects.create(usuario=self.cliente, rol='operador')
        self.producto = Producto.objects.create(
            nombre='Monitor profesional', sku='MON-001', precio='100000.00',
            costo='65000.00', stock=3, categoria='informatica',
        )
        self.venta = Venta.objects.create(
            usuario=self.cliente, total='100000.00', metodo_pago='transferencia',
            estado='completada', estado_pago='pagado', estado_envio='preparando',
        )
        DetalleVenta.objects.create(
            venta=self.venta, producto=self.producto, cantidad=1,
            precio_unitario='100000.00',
        )
        self.venta.refresh_from_db()
        self.client.force_login(self.admin)

    def test_renderiza_metricas_y_datos_reales(self):
        response = self.client.get(reverse('historial_ventas'), {'periodo': 'todo'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Panel vendedor')
        self.assertContains(response, self.venta.codigo)
        self.assertContains(response, 'Monitor profesional')
        self.assertContains(response, 'data-websocket-url=')
        self.assertContains(response, 'Actualización automática')
        self.assertEqual(response.context['metric_cards'][0]['value'], self.venta.total)
        self.assertEqual(response.context['metric_cards'][1]['value'], 35000)

    def test_busqueda_y_filtros_de_pedidos(self):
        response = self.client.get(reverse('historial_ventas'), {
            'periodo': 'todo', 'q': 'MON-001', 'envio': 'preparando',
        })

        self.assertEqual(response.context['page_obj'].paginator.count, 1)

    @patch('Tienda.views.publish_dashboard_event')
    def test_actualiza_estado_de_pago_y_envio(self, publish):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('historial_ventas'), {
                'venta_id': self.venta.pk,
                'estado_pago': 'pagado',
                'estado_envio': 'enviado',
            })

        self.assertRedirects(response, reverse('historial_ventas'))
        self.venta.refresh_from_db()
        self.assertEqual(self.venta.estado_envio, 'enviado')
        self.assertEqual(self.venta.estado, 'completada')
        publish.assert_called_once_with('sale.updated', self.venta.pk)

    def test_admin_guarda_transportista_y_tracking(self):
        self.client.post(reverse('historial_ventas'), {
            'venta_id': self.venta.pk,
            'estado_pago': 'pagado',
            'estado_envio': 'enviado',
            'transportista': 'Correo Argentino',
            'tracking': 'AR123456789',
        })

        self.venta.refresh_from_db()
        self.assertEqual(self.venta.transportista, 'Correo Argentino')
        self.assertEqual(self.venta.tracking, 'AR123456789')

    def test_cliente_solicita_y_admin_aprueba_devolucion(self):
        self.venta.estado_envio = 'entregado'
        self.venta.save(update_fields=['estado_envio'])
        payment = PagoSandbox.objects.create(
            venta=self.venta, proveedor='transferencia', estado='aprobado'
        )
        self.client.force_login(self.cliente)

        response = self.client.post(reverse('solicitar_devolucion', args=[self.venta.pk]), {
            'motivo': 'defectuoso', 'detalle': 'No enciende.',
        })

        self.assertRedirects(response, reverse('mis_compras'))
        request_return = SolicitudDevolucion.objects.get(venta=self.venta)
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('resolver_devolucion', args=[request_return.pk]),
            {'decision': 'aprobada', 'respuesta': 'Reembolso autorizado.'},
        )

        self.assertRedirects(response, reverse('historial_ventas'))
        request_return.refresh_from_db()
        self.venta.refresh_from_db()
        payment.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(request_return.estado, 'aprobada')
        self.assertEqual(self.venta.estado_pago, 'reembolsado')
        self.assertEqual(payment.estado, 'reembolsado')
        self.assertTrue(payment.stock_liberado)
        self.assertEqual(self.producto.stock, 4)

    @patch('Tienda.views._send_purchase_receipt_once', return_value=True)
    def test_admin_confirma_transferencia_pendiente(self, receipt):
        pending = Venta.objects.create(
            usuario=self.cliente, total='100000.00', metodo_pago='transferencia',
            estado='pendiente', estado_pago='pendiente', estado_envio='pendiente',
        )
        PagoSandbox.objects.create(venta=pending, proveedor='transferencia')

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('historial_ventas'), {
                'venta_id': pending.pk,
                'estado_pago': 'pagado',
                'estado_envio': 'preparando',
            })

        self.assertRedirects(response, reverse('historial_ventas'))
        pending.refresh_from_db()
        self.assertEqual(pending.estado, 'completada')
        self.assertEqual(pending.pago_sandbox.estado, 'aprobado')
        receipt.assert_called_once_with(pending)

    def test_cancelar_transferencia_pendiente_libera_stock(self):
        pending = Venta.objects.create(
            usuario=self.cliente, total='100000.00', metodo_pago='transferencia',
            estado='pendiente', estado_pago='pendiente', estado_envio='pendiente',
        )
        DetalleVenta.objects.create(
            venta=pending, producto=self.producto, cantidad=1,
            precio_unitario='100000.00',
        )
        PagoSandbox.objects.create(venta=pending, proveedor='transferencia')
        self.producto.stock -= 1
        self.producto.save(update_fields=['stock'])

        self.client.post(reverse('historial_ventas'), {
            'venta_id': pending.pk,
            'estado_pago': 'pendiente',
            'estado_envio': 'cancelado',
        })

        pending.refresh_from_db()
        self.producto.refresh_from_db()
        self.assertEqual(pending.estado_pago, 'rechazado')
        self.assertEqual(pending.estado, 'cancelada')
        self.assertEqual(self.producto.stock, 3)
        self.assertTrue(pending.pago_sandbox.stock_liberado)

    def test_exporta_csv(self):
        response = self.client.get(reverse('exportar_ventas_csv'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn(self.venta.codigo, response.content.decode('utf-8-sig'))

    def test_operador_no_puede_abrir_dashboard(self):
        self.client.force_login(self.cliente)

        response = self.client.get(reverse('historial_ventas'))

        self.assertEqual(response.status_code, 403)


class AsistenteGuiadoTests(TestCase):
    def setUp(self):
        self.product = Producto.objects.create(
            nombre='Mouse', precio='1000.00', stock=4, activo=True,
        )

    def test_responde_stock_con_datos_reales(self):
        response = self.client.post(reverse('asistente_consulta'), {'intent': 'stock'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('1 productos', response.json()['answer'])

    def test_no_acepta_preguntas_fuera_del_guion(self):
        response = self.client.post(reverse('asistente_consulta'), {'intent': 'inventado'})

        self.assertEqual(response.status_code, 400)


class DashboardRealtimeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin-websocket', email='ws@example.com', password='clave-segura'
        )
        Perfil.objects.create(usuario=self.admin, rol='admin')
        self.client.force_login(self.admin)
        self.session_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value

    def websocket_scope(self):
        headers = [
            (b'host', b'demo-store.trycloudflare.com'),
            (b'origin', b'https://demo-store.trycloudflare.com'),
            (
                b'cookie',
                f'{settings.SESSION_COOKIE_NAME}={self.session_key}'.encode(),
            ),
        ]
        return {
            'type': 'websocket', 'path': '/ws/ventas/',
            'headers': headers, 'scheme': 'wss',
        }

    def test_websocket_valida_sesion_admin(self):
        from .realtime import _authenticated_admin, _session_key

        session_key = _session_key(self.websocket_scope())

        self.assertEqual(session_key, self.session_key)
        self.assertEqual(_authenticated_admin(session_key), self.admin.pk)

    def test_websocket_exige_mismo_origen(self):
        from .realtime import _same_origin

        self.assertTrue(_same_origin(self.websocket_scope()))
        scope = self.websocket_scope()
        scope['headers'][1] = (b'origin', b'https://sitio-malicioso.example')
        self.assertFalse(_same_origin(scope))
