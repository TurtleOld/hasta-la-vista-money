# Generated by Django 4.2.10 on 2024-04-09 12:22

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('income', '0024_alter_income_user_alter_incomecategory_user'),
    ]

    operations = [
        migrations.AlterField(
            model_name='income',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='income_users',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='incomecategory',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='category_income_users',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
