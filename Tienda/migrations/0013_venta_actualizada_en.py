from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Tienda', '0012_alter_producto_imagen'),
    ]

    operations = [
        migrations.AddField(
            model_name='venta',
            name='actualizada_en',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
