"""Stub migration — replaced by 0001_squashed."""
from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('transactions', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = []
