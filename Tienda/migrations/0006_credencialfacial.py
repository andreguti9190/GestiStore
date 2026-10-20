from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('Tienda', '0005_credencial_passkey'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CredencialFacial',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('descriptor', models.JSONField()),
                ('modelo', models.CharField(default='vladmandic-face-api-1.7.15', max_length=80)),
                ('consentimiento_en', models.DateTimeField()),
                ('creada_en', models.DateTimeField(auto_now_add=True)),
                ('actualizada_en', models.DateTimeField(auto_now=True)),
                ('ultimo_uso', models.DateTimeField(blank=True, null=True)),
                ('usuario', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='credencial_facial', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Credencial facial',
                'verbose_name_plural': 'Credenciales faciales',
            },
        ),
    ]
