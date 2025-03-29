# Generated by Django 5.1.6 on 2025-03-29 21:49

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance_account', '0003_alter_account_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='type_account',
            field=models.CharField(
                choices=[
                    ('C', 'Кредитный счёт'),
                    ('D', 'Дебетовый счёт'),
                    ('CASH', 'Наличные'),
                ],
                default='D',
                verbose_name='Тип счёта',
            ),
        ),
    ]
