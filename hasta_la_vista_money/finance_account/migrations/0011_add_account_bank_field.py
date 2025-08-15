# Generated manually for adding bank field to Account model

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance_account', '0010_alter_account_currency_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='bank',
            field=models.CharField(
                choices=[
                    ('-', '—'),
                    ('SBERBANK', 'Сбербанк'),
                ],
                default='-',
                help_text='Банк, выпустивший карту или обслуживающий счёт',
                verbose_name='Банк',
            ),
        ),
    ]
