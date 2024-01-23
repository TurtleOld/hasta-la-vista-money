# Generated by Django 4.2.6 on 2023-10-15 23:01

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "account",
            "0011_alter_transfermoneylog_options_alter_account_user_and_more",
        ),
        ("users", "0007_alter_user_policy"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="policy",
        ),
        migrations.AlterField(
            model_name="telegramuser",
            name="selected_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="selected_account_telegram_users",
                to="account.account",
            ),
        ),
        migrations.AlterField(
            model_name="telegramuser",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="telegram_users",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
