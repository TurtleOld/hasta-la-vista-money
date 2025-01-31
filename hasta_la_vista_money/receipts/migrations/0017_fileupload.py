# Generated by Django 4.2.11 on 2024-04-09 21:11

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('account', '0029_alter_account_user_alter_transfermoneylog_user'),
        ('receipts', '0016_alter_customer_user_alter_product_user_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='FileUpload',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('file', models.FileField(upload_to='media/')),
                (
                    'account',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to='account.account',
                    ),
                ),
            ],
        ),
    ]
