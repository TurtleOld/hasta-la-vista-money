# Generated by Django 4.2.17 on 2025-02-09 18:15

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Account',
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
                (
                    'name_account',
                    models.CharField(default='Основной счёт', max_length=250),
                ),
                (
                    'balance',
                    models.DecimalField(decimal_places=2, default=0, max_digits=20),
                ),
                (
                    'currency',
                    models.CharField(
                        choices=[
                            ('RUB', 'Российский рубль'),
                            ('USD', 'Доллар США'),
                            ('EUR', 'Евро'),
                            ('GBP', 'Британский фунт'),
                            ('CZK', 'Чешская крона'),
                            ('PLN', 'Польский злотый'),
                            ('TRY', 'Турецкая лира'),
                            ('CNH', 'Китайский юань'),
                        ]
                    ),
                ),
                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name='Date created'
                    ),
                ),
            ],
            options={
                'db_table': 'account',
                'ordering': ['name_account'],
            },
        ),
        migrations.CreateModel(
            name='TransferMoneyLog',
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
                ('amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('exchange_date', models.DateTimeField()),
                ('notes', models.TextField(blank=True)),
                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name='Date created'
                    ),
                ),
                (
                    'from_account',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='from_account',
                        to='finance_account.account',
                    ),
                ),
                (
                    'to_account',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='to_account',
                        to='finance_account.account',
                    ),
                ),
            ],
            options={
                'ordering': ['-exchange_date'],
            },
        ),
    ]
