# Generated by Django 4.2.9 on 2024-01-25 21:47

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        (
            'expense',
            '0017_remove_expensecategory_parent_category_self_and_more',
        ),
    ]

    operations = [
        migrations.AlterField(
            model_name='expensecategory',
            name='parent_category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='subcategories',
                to='expense.expensecategory',
            ),
        ),
    ]
