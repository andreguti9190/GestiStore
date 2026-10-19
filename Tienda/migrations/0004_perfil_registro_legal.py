from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Tienda', '0003_alter_producto_categoria'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfil',
            name='fecha_nacimiento',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='perfil',
            name='registro_verificado_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='perfil',
            name='terminos_aceptados_en',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='perfil',
            name='terminos_version',
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
