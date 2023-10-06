# Generated by Django 4.2.6 on 2023-10-06 16:22

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("expense", "0004_expense_expense_exp_date_5e5d86_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="expense",
            name="amount",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=10
            ),
            preserve_default=False,
        ),
    ]
