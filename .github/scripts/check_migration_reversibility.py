from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import django
from django.db import connections
from django.db.migrations.loader import MigrationLoader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANAGE_PY = PROJECT_ROOT / 'manage.py'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'migration_paths',
        nargs='*',
        help='Changed migration file paths to verify.',
    )
    return parser.parse_args()


def to_migration_key(migration_path: str) -> tuple[str, str]:
    path = Path(migration_path)
    return path.parts[-3], path.stem


def get_previous_migration(
    loader: MigrationLoader,
    migration_key: tuple[str, str],
) -> str:
    migration = loader.disk_migrations[migration_key]
    same_app_dependencies = [
        dependency_name
        for dependency_app, dependency_name in migration.dependencies
        if dependency_app == migration_key[0]
    ]

    if not same_app_dependencies:
        return 'zero'

    if len(same_app_dependencies) > 1:
        msg = (
            'Expected a linear migration history, got multiple '
            f'parents for {migration_key[0]}.{migration_key[1]}: '
            f'{same_app_dependencies}'
        )
        raise RuntimeError(msg)

    return same_app_dependencies[0]


def run_manage_command(
    env: dict[str, str],
    app_label: str,
    migration_name: str,
) -> tuple[bool, str]:
    # The command is fixed; only app and migration identifiers vary.
    result = subprocess.run(
        [
            sys.executable,
            str(MANAGE_PY),
            'migrate',
            app_label,
            migration_name,
            '--noinput',
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f'{result.stdout}{result.stderr}'
    return result.returncode == 0, output


def build_temp_env(database_path: str) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault(
        'SECRET_KEY',
        '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
    )
    env.setdefault('ALLOWED_HOSTS', 'localhost,127.0.0.1')
    env.setdefault('ACCESS_TOKEN_LIFETIME', '60')
    env.setdefault('REFRESH_TOKEN_LIFETIME', '7')
    env.setdefault('REDIS_LOCATION', 'redis://localhost:6379/1')
    env['DATABASE_URL'] = f'sqlite:///{database_path}'
    env['CI'] = 'true'
    return env


def main() -> int:
    args = parse_args()
    migration_paths = [
        path
        for path in args.migration_paths
        if path.endswith('.py') and not path.endswith('__init__.py')
    ]

    if not migration_paths:
        sys.stdout.write('No changed migration files to verify.\n')
        return 0

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.django.base')
    django.setup()
    loader = MigrationLoader(connections['default'], ignore_no_migrations=True)

    failures: list[str] = []

    for migration_path in migration_paths:
        app_label, migration_name = to_migration_key(migration_path)
        previous_migration = get_previous_migration(
            loader,
            (app_label, migration_name),
        )

        with tempfile.TemporaryDirectory(
            prefix='hlvm-migration-check-',
        ) as temp_dir:
            database_path = str(Path(temp_dir) / 'db.sqlite3')
            env = build_temp_env(database_path)

            migrated, migrate_output = run_manage_command(
                env,
                app_label,
                migration_name,
            )
            if not migrated:
                failures.append(
                    f'{app_label}.{migration_name}: apply failed\n'
                    f'{migrate_output}',
                )
                continue

            rolled_back, rollback_output = run_manage_command(
                env,
                app_label,
                previous_migration,
            )
            if not rolled_back:
                failures.append(
                    f'{app_label}.{migration_name}: rollback to '
                    f'{previous_migration} failed\n{rollback_output}',
                )

    if failures:
        sys.stderr.write('Rollback-risk migrations detected:\n')
        for failure in failures:
            sys.stderr.write(f' - {failure}\n')
        return 1

    sys.stdout.write(
        'Rollback check passed for '
        f'{len(migration_paths)} changed migrations.\n',
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
