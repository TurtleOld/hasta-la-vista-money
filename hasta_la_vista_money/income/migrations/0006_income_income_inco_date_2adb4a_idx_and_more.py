# Generated by Django 4.2.5 on 2023-09-25 00:15

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('income', '0005_alter_income_user'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='income',
            index=models.Index(fields=['-date'], name='income_inco_date_2adb4a_idx'),
        ),
        migrations.AddIndex(
            model_name='income',
            index=models.Index(fields=['amount'], name='income_inco_amount_358474_idx'),
        ),
        migrations.AddIndex(
            model_name='incometype',
            index=models.Index(fields=['name'], name='income_inco_name_19eb49_idx'),
        ),
    ]
