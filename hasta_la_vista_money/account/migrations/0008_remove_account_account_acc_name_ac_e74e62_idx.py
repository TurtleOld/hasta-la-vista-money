# Generated by Django 4.2.5 on 2023-09-25 00:22

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("account", "0007_account_account_acc_name_ac_e74e62_idx"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="account",
            name="account_acc_name_ac_e74e62_idx",
        ),
    ]
