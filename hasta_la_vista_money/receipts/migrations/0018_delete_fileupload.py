# Generated by Django 4.2.11 on 2024-04-09 21:21

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("receipts", "0017_fileupload"),
    ]

    operations = [
        migrations.DeleteModel(
            name="FileUpload",
        ),
    ]
