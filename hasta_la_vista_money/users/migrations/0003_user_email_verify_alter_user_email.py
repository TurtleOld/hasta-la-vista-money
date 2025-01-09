# Generated by Django 4.2.4 on 2023-08-13 16:38

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0002_user_policy'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='email_verify',
            field=models.BooleanField(null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(max_length=254, null=True, unique=True),
        ),
    ]
