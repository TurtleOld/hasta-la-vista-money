# Generated by Django 5.2.4 on 2025-07-07 21:16

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0002_user_theme'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='theme',
            field=models.CharField(default='dark', max_length=10),
        ),
    ]
