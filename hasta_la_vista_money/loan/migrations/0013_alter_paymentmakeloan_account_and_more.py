# Generated by Django 4.2.5 on 2023-10-01 18:48

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('account', '0009_account_account_acc_name_ac_e74e62_idx'),
        ('loan', '0012_alter_loan_options_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paymentmakeloan',
            name='account',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to='account.account',
            ),
        ),
        migrations.AlterField(
            model_name='paymentmakeloan',
            name='loan',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, to='loan.loan'
            ),
        ),
    ]
