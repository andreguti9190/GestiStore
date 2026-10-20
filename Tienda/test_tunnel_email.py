import importlib
import smtplib
from email.mime.image import MIMEImage
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, RequestFactory, override_settings
from django.urls import clear_url_caches, reverse

from .emails import (
    _login_location,
    _login_map_preview,
    send_login_code,
    send_login_notification,
)
from .models import Perfil, Producto, Venta
from scripts.configurar_correo import save_mail_settings, main as configure_mail


class TunnelMediaTests(TestCase):
    def test_upload_and_download_image_with_debug_disabled(self):
        import GestiStore.urls as urls
        with TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as directory:
            try:
                with override_settings(DEBUG=False, SERVE_MEDIA_FILES=True, MEDIA_ROOT=directory):
                    importlib.reload(urls)
                    clear_url_caches()
                    user = User.objects.create_user(username='image_admin', password='StrongPassword123!')
                    Perfil.objects.create(usuario=user, rol='admin')
                    self.client.force_login(user)
                    output = BytesIO()
                    Image.new('RGB', (4, 4), 'blue').save(output, format='PNG')
                    contents = output.getvalue()
                    response = self.client.post(reverse('crear_producto'), {
                        'nombre': 'Imagen de prueba', 'descripcion': 'Prueba de subida',
                        'precio': '100', 'stock': '2', 'peso_kg': '1',
                        'categoria': 'informatica', 'activo': 'on',
                        'imagen': SimpleUploadedFile('prueba.png', contents, content_type='image/png'),
                    })
                    self.assertEqual(response.status_code, 302)
                    product = Producto.objects.get(nombre='Imagen de prueba')
                    self.assertTrue(Path(product.imagen.path).is_file())
                    self.client.logout()
                    response = self.client.get(product.imagen.url)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response['Content-Type'], 'image/png')
                    self.assertEqual(b''.join(response.streaming_content), contents)
                    response.close()
                    self.assertEqual(self.client.get('/media/').status_code, 404)
                    self.assertEqual(self.client.get('/media/%2e%2e/GestiStore/settings.py').status_code, 400)
            finally:
                importlib.reload(urls)
                clear_url_caches()

    def test_media_requires_explicit_demo_flag_when_debug_is_false(self):
        import GestiStore.urls as urls
        try:
            with override_settings(DEBUG=False, SERVE_MEDIA_FILES=False):
                importlib.reload(urls)
                clear_url_caches()
                self.assertEqual(self.client.get('/media/productos/prueba.png').status_code, 404)
        finally:
            importlib.reload(urls)
            clear_url_caches()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class LoginEmailTests(SimpleTestCase):
    def setUp(self):
        self.user = User(username='cliente', email='cliente@example.com')

    @patch('Tienda.emails.urlopen', side_effect=OSError('Sin conexión'))
    def test_location_failure_does_not_prevent_login_email(self, _lookup):
        request = RequestFactory().get('/', REMOTE_ADDR='8.8.8.8')
        self.assertEqual(send_login_notification(request, self.user, 'Reconocimiento facial'), 1)
        self.assertIn('No disponible', mail.outbox[0].body)
        self.assertIn(
            'Mapa no disponible para este acceso',
            mail.outbox[0].alternatives[0].content,
        )
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    @patch('Tienda.emails.urlopen')
    def test_unexpected_location_payload_does_not_break_notice(self, lookup):
        lookup.return_value.__enter__.return_value.read.return_value = b'[]'
        self.assertIsNone(_login_location('8.8.8.8'))

    @patch('Tienda.emails._login_map_preview')
    @patch('Tienda.emails._login_location')
    def test_login_email_includes_inline_map_and_full_map_link(self, location, preview):
        location.return_value = {
            'label': 'Buenos Aires, Argentina',
            'map_url': 'https://www.openstreetmap.org/#map=8/-34.6/-58.4',
            'latitude': -34.6,
            'longitude': -58.4,
        }
        image = MIMEImage(b'preview', _subtype='png')
        image.add_header('Content-ID', '<ubicacion-aproximada>')
        preview.return_value = image

        request = RequestFactory().get('/', REMOTE_ADDR='8.8.8.8')
        self.assertEqual(send_login_notification(request, self.user, 'Contraseña'), 1)

        html = mail.outbox[0].alternatives[0].content
        self.assertIn('cid:ubicacion-aproximada', html)
        self.assertIn('Abrir mapa completo', html)
        self.assertIn(location.return_value['map_url'], html)
        self.assertEqual(mail.outbox[0].attachments[0]['Content-ID'], '<ubicacion-aproximada>')

    @patch('Tienda.emails._read_map_tile')
    def test_map_preview_is_generated_as_inline_png(self, read_tile):
        tile = BytesIO()
        Image.new('RGB', (256, 256), '#dbe8d2').save(tile, format='PNG')
        read_tile.return_value = tile.getvalue()

        preview = _login_map_preview({
            'latitude': -34.6,
            'longitude': -58.4,
        })

        self.assertIsNotNone(preview)
        self.assertEqual(preview['Content-ID'], '<ubicacion-aproximada>')
        rendered = Image.open(BytesIO(preview.get_payload(decode=True)))
        self.assertEqual(rendered.size, (512, 300))

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
        EMAIL_HOST='smtp.gmail.com', EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='',
    )
    @patch('smtplib.SMTP')
    def test_missing_credentials_report_actionable_error_without_smtp(self, smtp):
        with self.assertRaisesMessage(ImproperlyConfigured, 'contraseña de aplicación'):
            send_login_code(self.user, '123456')
        smtp.assert_not_called()

    @patch('Tienda.emails.EmailMultiAlternatives.send', return_value=0)
    def test_zero_messages_is_not_reported_as_success(self, _send):
        with self.assertRaises(RuntimeError):
            send_login_code(self.user, '123456')


class MailConfigurationTests(SimpleTestCase):
    def test_saves_mail_configuration_and_preserves_other_settings(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as directory:
            path = Path(directory) / '.env'
            path.write_text('# local\nPUBLIC_BASE_URL=https://example.test\nEMAIL_HOST_USER=old@example.com\n', encoding='utf-8')
            save_mail_settings(path, 'sender@example.com', 'abcdefghijklmnop')
            result = path.read_text(encoding='utf-8')
            self.assertIn('PUBLIC_BASE_URL=https://example.test', result)
            self.assertIn('EMAIL_HOST_USER=sender@example.com', result)
            self.assertEqual(result.count('EMAIL_HOST_USER='), 1)
            self.assertFalse(list(Path(directory).glob('.mail-config-*')))

    @patch('scripts.configurar_correo.save_mail_settings')
    @patch('scripts.configurar_correo.smtplib.SMTP')
    @patch('scripts.configurar_correo.getpass.getpass', return_value='abcdefghijklmnop')
    @patch('builtins.input', return_value='sender@example.com')
    def test_rejected_credentials_do_not_replace_configuration(self, _input, _getpass, smtp, save):
        smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b'rejected')
        with self.assertRaises(smtplib.SMTPAuthenticationError):
            configure_mail()
        save.assert_not_called()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ReceiptResendTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner', email='owner@example.com')
        self.sale = Venta.objects.create(usuario=self.user, total=100, metodo_pago='transferencia')
        self.client.force_login(self.user)

    def test_owner_can_resend_with_cooldown(self):
        url = reverse('reenviar_comprobante', args=[self.sale.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        self.assertRedirects(response, reverse('mis_compras'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn(self.sale.codigo, mail.outbox[0].subject)
        self.client.post(url)
        self.assertEqual(len(mail.outbox), 1)

    def test_other_account_cannot_resend_my_receipt(self):
        other = User.objects.create_user(username='other', email='other@example.com')
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse('reenviar_comprobante', args=[self.sale.pk])).status_code, 404)
        self.assertEqual(len(mail.outbox), 0)
