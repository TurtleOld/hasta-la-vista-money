# Generated by Django 4.2.5 on 2023-09-20 23:51

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('loan', '0009_alter_paymentmakeloan_loan'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paymentmakeloan',
            name='loan',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to='loan.loan'
            ),
        ),
    ]
