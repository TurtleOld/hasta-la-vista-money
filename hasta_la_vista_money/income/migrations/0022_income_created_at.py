# Generated by Django 4.2.10 on 2024-03-22 10:04

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('income', '0021_alter_incomecategory_parent_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='income',
            name='created_at',
            field=models.DateTimeField(
                auto_now_add=True, null=True, verbose_name='Date created'
            ),
        ),
    ]
