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
from .models import CredencialFacial, CredencialPasskey, DetalleVenta, Perfil, Producto, Venta


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

    def test_menor_de_18_no_puede_registrarse(self):
        fecha_menor = timezone.localdate().replace(year=timezone.localdate().year - 17)

        response = self.client.post(
            reverse('registro'),
            self.datos_validos(fecha_nacimiento=fecha_menor.isoformat()),
        )

        self.assertContains(response, 'Tenés que ser mayor de 18 años')
        self.assertFalse(User.objects.filter(username='cliente_nuevo').exists())
        self.assertEqual(len(mail.outbox), 0)

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

    def test_compra_envia_comprobante_con_detalle(self):
        response = self.client.post(reverse('procesar_pago'), {
            'metodo_pago': 'transferencia',
            'verification_method': 'password',
            'account_password': 'UnaClaveSegura123!',
        })

        self.assertRedirects(response, reverse('compra_exitosa'))
        venta = Venta.objects.get(usuario=self.user)
        self.assertEqual(venta.total, 25000)
        self.assertEqual(DetalleVenta.objects.filter(venta=venta).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(venta.codigo, mail.outbox[0].subject)
        self.assertIn('Teclado', mail.outbox[0].body)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)

    @patch('Tienda.views.send_purchase_receipt', side_effect=Exception('SMTP caído'))
    def test_falla_de_email_no_anula_la_compra(self, _send):
        response = self.client.post(reverse('procesar_pago'), {
            'metodo_pago': 'transferencia',
            'verification_method': 'password',
            'account_password': 'UnaClaveSegura123!',
        })

        self.assertEqual(self.client.session['comprobante_enviado'], False)
        self.assertRedirects(response, reverse('compra_exitosa'))
        self.assertEqual(Venta.objects.filter(usuario=self.user).count(), 1)
