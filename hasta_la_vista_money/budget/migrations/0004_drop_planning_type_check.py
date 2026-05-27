"""Drop the planning_category_matches_type CHECK constraint.

The constraint was added by original migration 0006 but is absent from the
current model (it was not carried forward into 0001_squashed). On databases
that went through the original migration sequence the constraint is still
present in the schema and blocks INSERT.

Safe to apply on any database:
- Constraint present  → dropped via table-rebuild (SQLite) or ALTER TABLE.
- Constraint absent   → no-op, migration is recorded and skipped.
"""

from django.db import migrations, models


def _drop_constraint_if_exists(apps, schema_editor):
    db = schema_editor.connection

    if db.vendor == 'sqlite':
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='budget_planning'"
            )
            row = cursor.fetchone()
            if row is None or 'planning_category_matches_type' not in (row[0] or ''):
                return

        Planning = apps.get_model('budget', 'Planning')
        # The check= expression is a placeholder; only name matters for removal.
        # SQLite's remove_constraint calls _remake_table which rebuilds the table
        # using model._meta.constraints — which does NOT include the old constraint.
        constraint = models.CheckConstraint(
            condition=models.Q(id__isnull=False),
            name='planning_category_matches_type',
        )
        schema_editor.remove_constraint(Planning, constraint)
    else:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_name = 'budget_planning' "
                "AND constraint_name = 'planning_category_matches_type'",
            )
            if not cursor.fetchone():
                return

        schema_editor.execute(
            'ALTER TABLE budget_planning DROP CONSTRAINT planning_category_matches_type',
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('budget', '0003_add_planning_category'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunPython(
                    _drop_constraint_if_exists,
                    migrations.RunPython.noop,
                ),
            ],
        ),
    ]
