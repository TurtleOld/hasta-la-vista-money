"""Merge statement identity/retention and balance verification branches."""

from django.db import migrations


class Migration(migrations.Migration):
    """Join the two independently applied users migration leaves."""

    dependencies = [
        ('users', '0026_statement_balance_verification'),
        ('users', '0028_user_statement_retention_days'),
    ]

    operations: list[migrations.operations.base.Operation] = []
