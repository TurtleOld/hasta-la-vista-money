# Generated by Django 4.2.10 on 2024-03-18 20:37

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('account', '0019_alter_account_currency_alter_transfermoneylog_notes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transfermoneylog',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='transfer_money',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
