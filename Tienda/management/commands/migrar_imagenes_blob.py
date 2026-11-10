import os
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError

from Tienda.models import Producto


class Command(BaseCommand):
    help = 'Sube a Vercel Blob las imágenes locales referenciadas por productos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra qué imágenes se migrarían sin subirlas.',
        )

    def handle(self, *args, **options):
        if default_storage.__class__.__name__ != 'VercelBlobStorage':
            raise CommandError(
                'El almacenamiento activo no es Vercel Blob. Cargá el entorno '
                'de Vercel con GESTISTORE_ENV_FILE antes de ejecutar el comando.'
            )
        if not (
            os.getenv('BLOB_READ_WRITE_TOKEN')
            or os.getenv('VERCEL_BLOB_READ_WRITE_TOKEN')
            or os.getenv('VERCEL_OIDC_TOKEN')
        ):
            raise CommandError(
                'Para subir desde esta PC necesitás BLOB_READ_WRITE_TOKEN. '
                'Crealo en el Blob Store de Vercel y guardalo sólo en .env.vercel.'
            )

        media_root = Path(settings.MEDIA_ROOT).resolve()
        migrated = missing = skipped = 0
        for product in Producto.objects.exclude(imagen='').iterator():
            name = product.imagen.name
            if name.startswith(('https://', 'http://')):
                skipped += 1
                continue

            source = (media_root / name).resolve()
            try:
                source.relative_to(media_root)
            except ValueError as error:
                raise CommandError(f'Ruta de imagen inválida: {name}') from error

            if not source.is_file():
                self.stderr.write(self.style.WARNING(f'No encontrada: {source}'))
                missing += 1
                continue

            self.stdout.write(f'{product.pk}: {name}')
            if options['dry_run']:
                continue
            with source.open('rb') as handle:
                stored_name = default_storage.save(name, File(handle, name=source.name))
            Producto.objects.filter(pk=product.pk).update(imagen=stored_name)
            migrated += 1

        if options['dry_run']:
            self.stdout.write(self.style.SUCCESS('Simulación terminada; no se subió ningún archivo.'))
            return
        self.stdout.write(self.style.SUCCESS(
            f'Migración terminada: {migrated} subida(s), {skipped} ya remota(s), '
            f'{missing} faltante(s).'
        ))
