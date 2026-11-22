from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('users', '0028_merge_statement_replay'),
        ('users', '0028_user_statement_retention_days'),
    ]

    operations = []
