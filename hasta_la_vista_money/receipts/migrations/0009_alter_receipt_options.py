# Generated by Django 4.2.5 on 2023-09-20 21:11

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('receipts', '0008_rename_nds_10_receipt_nds10_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='receipt',
            options={'ordering': ['-receipt_date']},
        ),
    ]
