from django.db import migrations, models
import django.db.models.deletion

import hasta_la_vista_money.finance_account.models


class Migration(migrations.Migration):
    dependencies = [
        ('finance_account', '0021_migrate_account_bank_to_fk'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='bank',
            field=models.ForeignKey(
                default=hasta_la_vista_money.finance_account.models._get_default_bank_pk,
                on_delete=django.db.models.deletion.PROTECT,
                to='finance_account.Bank',
                verbose_name='Банк',
                help_text='Банк, выпустивший карту или обслуживающий счёт',
            ),
        ),
    ]
