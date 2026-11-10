from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Tienda', '0011_perfil_verificacion_dos_pasos'),
    ]

    operations = [
        migrations.AlterField(
            model_name='producto',
            name='imagen',
            field=models.ImageField(
                blank=True,
                max_length=500,
                null=True,
                upload_to='productos/',
            ),
        ),
    ]
