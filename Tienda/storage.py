"""Almacenamiento persistente de imágenes para despliegues en Vercel."""

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible
from vercel.blob import sync as blob


@deconstructible
class VercelBlobStorage(Storage):
    """Guarda imágenes públicas en Vercel Blob y conserva su URL en Django."""

    access = 'public'

    def _open(self, name, mode='rb'):
        if mode not in {'r', 'rb'}:
            raise ValueError('Vercel Blob solamente admite lectura desde Django.')
        result = blob.get_blob(name, access=self.access)
        return ContentFile(result.body, name=name)

    def _save(self, name, content):
        size = getattr(content, 'size', None)
        body = content if size is not None else content.read()
        result = blob.put_blob(
            name,
            body,
            access=self.access,
            content_length=size,
            content_type=getattr(content, 'content_type', None),
            add_random_suffix=True,
            cache_control_max_age=31_536_000,
        )
        return result.url

    def delete(self, name):
        if name:
            blob.delete_blob(name)

    def exists(self, name):
        # Cada carga recibe un sufijo aleatorio en Blob, por lo que no puede
        # colisionar aunque dos imágenes compartan el nombre original.
        return False

    def size(self, name):
        return blob.head_blob(name).size

    def url(self, name):
        if name.startswith(('https://', 'http://')):
            return name
        return blob.head_blob(name).url
