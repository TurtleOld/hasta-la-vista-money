# Generated by Django 4.2.17 on 2025-02-19 14:45

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('receipts', '0002_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='seller',
            name='retail_place',
            field=models.CharField(blank=True, default='Нет данных', max_length=1000),
        ),
        migrations.AlterField(
            model_name='seller',
            name='retail_place_address',
            field=models.CharField(blank=True, default='Нет данных', max_length=1000),
        ),
    ]
