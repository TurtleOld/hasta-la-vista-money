"""Add category_id to budget_planning if the column is missing.

This migration is safe to apply against any existing database:
- If category_id already exists (squash was cleanly applied): the
  database operation is a no-op.
- If category_id is missing (very old schema before the squash): the
  column is added without data loss.
"""

import django.db.models.deletion
from django.db import migrations, models


def _add_column_if_missing(apps, schema_editor):
    db = schema_editor.connection
    with db.cursor() as cursor:
        if db.vendor == 'sqlite':
            cursor.execute("PRAGMA table_info(budget_planning)")
            has_column = any(row[1] == 'category_id' for row in cursor.fetchall())
        else:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'budget_planning' AND column_name = 'category_id'",
            )
            has_column = bool(cursor.fetchone())

    if has_column:
        return

    if db.vendor == 'sqlite':
        schema_editor.execute(
            "ALTER TABLE budget_planning ADD COLUMN "
            "category_id integer REFERENCES transactions_category(id) ON DELETE CASCADE",
        )
    else:
        schema_editor.execute(
            "ALTER TABLE budget_planning ADD COLUMN "
            "category_id bigint REFERENCES transactions_category(id) ON DELETE CASCADE",
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('budget', '0002_budget'),
        ('transactions', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunPython(
                    _add_column_if_missing,
                    migrations.RunPython.noop,
                ),
            ],
        ),
    ]
