# Generated by Django 4.2.10 on 2024-03-18 20:52

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('account', '0022_transfermoneylog_user'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='transfermoneylog',
            name='user',
        ),
    ]
