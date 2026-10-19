import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlparse

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import DetalleVenta, Perfil, Producto, Venta


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

    def test_terminos_son_publicos(self):
        response = self.client.get(reverse('terminos_y_condiciones'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Términos y Condiciones')
        self.assertContains(response, 'Ley 25.326')


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
        })

        self.assertEqual(self.client.session['comprobante_enviado'], False)
        self.assertRedirects(response, reverse('compra_exitosa'))
        self.assertEqual(Venta.objects.filter(usuario=self.user).count(), 1)
