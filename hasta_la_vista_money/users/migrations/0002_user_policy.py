# Generated by Django 4.2.4 on 2023-08-13 14:03

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='policy',
            field=models.BooleanField(null=True),
        ),
    ]
