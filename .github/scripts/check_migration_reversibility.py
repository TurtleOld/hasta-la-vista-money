from __future__ import annotations

import os
import sys
from io import StringIO

import django
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.db.migrations.loader import MigrationLoader


def main() -> int:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.django.base')
    django.setup()

    connection = connections['default']
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    failures: list[str] = []

    migrations = sorted(
        (
            key
            for key, migration in loader.disk_migrations.items()
            if migration.__module__.startswith('hasta_la_vista_money.')
        ),
    )

    for app_label, migration_name in migrations:
        try:
            call_command(
                'sqlmigrate',
                app_label,
                migration_name,
                backwards=True,
                stdout=StringIO(),
            )
        except (CommandError, Exception) as exc:
            failures.append(f'{app_label}.{migration_name}: {exc}')

    if failures:
        sys.stderr.write('Irreversible or rollback-risk migrations detected:\n')
        for failure in failures:
            sys.stderr.write(f' - {failure}\n')
        return 1

    sys.stdout.write(
        f'Checked {len(migrations)} project migrations for reverse SQL.\n',
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
