# Generated by Django 4.2.17 on 2025-02-09 18:15

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('finance_account', '0002_initial'),
        ('income', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='incomecategory',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='category_income_users',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='income',
            name='account',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='income_accounts',
                to='finance_account.account',
            ),
        ),
        migrations.AddField(
            model_name='income',
            name='category',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='income_categories',
                to='income.incomecategory',
            ),
        ),
        migrations.AddField(
            model_name='income',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='income_users',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name='incomecategory',
            index=models.Index(fields=['name'], name='income_inco_name_cd576f_idx'),
        ),
        migrations.AddIndex(
            model_name='income',
            index=models.Index(fields=['-date'], name='income_inco_date_2adb4a_idx'),
        ),
        migrations.AddIndex(
            model_name='income',
            index=models.Index(fields=['amount'], name='income_inco_amount_358474_idx'),
        ),
    ]
