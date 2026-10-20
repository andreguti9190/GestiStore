from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('Tienda', '0004_perfil_registro_legal'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CredencialPasskey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(default='Este dispositivo', max_length=80)),
                ('credential_id', models.BinaryField(unique=True)),
                ('public_key', models.BinaryField()),
                ('sign_count', models.PositiveBigIntegerField(default=0)),
                ('transports', models.JSONField(blank=True, default=list)),
                ('device_type', models.CharField(blank=True, max_length=30)),
                ('backed_up', models.BooleanField(default=False)),
                ('creada_en', models.DateTimeField(auto_now_add=True)),
                ('ultimo_uso', models.DateTimeField(blank=True, null=True)),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='credenciales_passkey', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Credencial Face ID / passkey',
                'verbose_name_plural': 'Credenciales Face ID / passkey',
                'ordering': ['-creada_en'],
            },
        ),
    ]
