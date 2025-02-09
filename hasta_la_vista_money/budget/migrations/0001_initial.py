# Generated by Django 4.2.17 on 2025-02-09 18:15

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='DateList',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('date', models.DateTimeField()),
                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name='Date created'
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name='Planning',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'created_at',
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name='Date created'
                    ),
                ),
            ],
        ),
    ]
