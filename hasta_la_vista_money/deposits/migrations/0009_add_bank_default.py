from django.db import migrations, models
import django.db.models.deletion

import hasta_la_vista_money.finance_account.models


class Migration(migrations.Migration):
    dependencies = [
        ('deposits', '0008_migrate_deposit_bank_to_fk'),
        ('finance_account', '0022_add_bank_default'),
    ]

    operations = [
        migrations.AlterField(
            model_name='deposit',
            name='bank',
            field=models.ForeignKey(
                default=hasta_la_vista_money.finance_account.models._get_default_bank_pk,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='deposits',
                to='finance_account.Bank',
                verbose_name='Банк',
            ),
        ),
    ]
