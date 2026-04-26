from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import django
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.utils import load_backend


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
) -> str | None:
    migration = loader.disk_migrations[migration_key]
    same_app_dependencies = [
        dependency_name
        for dependency_app, dependency_name in migration.dependencies
        if dependency_app == migration_key[0]
    ]

    if not same_app_dependencies:
        return None

    if len(same_app_dependencies) > 1:
        msg = (
            'Expected a linear migration history, got multiple '
            f'parents for {migration_key[0]}.{migration_key[1]}: '
            f'{same_app_dependencies}'
        )
        raise RuntimeError(msg)

    return same_app_dependencies[0]


def configure_environment_defaults() -> None:
    os.environ.setdefault(
        'SECRET_KEY',
        '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
    )
    os.environ.setdefault('ALLOWED_HOSTS', 'localhost,127.0.0.1')
    os.environ.setdefault('ACCESS_TOKEN_LIFETIME', '60')
    os.environ.setdefault('REFRESH_TOKEN_LIFETIME', '7')
    os.environ.setdefault('REDIS_LOCATION', 'redis://localhost:6379/1')
    os.environ.setdefault('CI', 'true')


def build_temp_database_settings(database_path: str) -> dict[str, Any]:
    return {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': database_path,
        'ATOMIC_REQUESTS': False,
        'AUTOCOMMIT': True,
        'CONN_MAX_AGE': 0,
        'CONN_HEALTH_CHECKS': False,
        'OPTIONS': {},
        'TIME_ZONE': None,
        'USER': '',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
        'TEST': {
            'CHARSET': None,
            'COLLATION': None,
            'MIGRATE': True,
            'MIRROR': None,
            'NAME': None,
        },
    }


def create_temp_connection(database_path: str):
    settings_dict = build_temp_database_settings(database_path)
    backend = load_backend(settings_dict['ENGINE'])
    return backend.DatabaseWrapper(settings_dict, 'migration_check')


def migrate_target(
    database_path: str,
    app_label: str,
    migration_name: str | None,
) -> None:
    connection = create_temp_connection(database_path)

    try:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([(app_label, migration_name)])
    finally:
        connection.close()


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

    configure_environment_defaults()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.django.base')
    django.setup()

    loader_connection = create_temp_connection(':memory:')
    try:
        loader = MigrationLoader(loader_connection, ignore_no_migrations=True)
    finally:
        loader_connection.close()

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

            try:
                migrate_target(database_path, app_label, migration_name)
            except Exception as exc:
                failures.append(
                    f'{app_label}.{migration_name}: apply failed\n'
                    f'{type(exc).__name__}: {exc}',
                )
                continue

            try:
                migrate_target(database_path, app_label, previous_migration)
            except Exception as exc:
                rollback_target = previous_migration or 'zero'
                failures.append(
                    f'{app_label}.{migration_name}: rollback to '
                    f'{rollback_target} failed\n'
                    f'{type(exc).__name__}: {exc}',
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
