from os import environ

import structlog
from decouple import config

logger = structlog.get_logger(__name__)


class EnvironmentValidator:
    def validate(self) -> bool:
        if (
            environ.get('CI')
            or environ.get('GITHUB_ACTIONS')
            or environ.get('DOCKER_BUILD')
            or environ.get('SECRET_KEY') == 'build-time-secret-key'
        ):
            return True

        valid = True
        if not config('SECRET_KEY', cast=str, default=''):
            valid = False
            logger.warning(
                'Required environment variable is not set',
                variable='SECRET_KEY',
                hint='Use make secretkey to generate it',
            )
        if not config('ALLOWED_HOSTS', cast=str, default=''):
            valid = False
            logger.warning(
                'Required environment variable is not set',
                variable='ALLOWED_HOSTS',
                hint='Set it to a comma-separated list of hosts',
            )
        if not config('DATABASE_URL', cast=str, default=''):
            valid = False
            logger.warning(
                'Required environment variable is not set',
                variable='DATABASE_URL',
                hint='Set it to a valid database URL',
            )

        debug_mode = config('DEBUG', default=False, cast=bool)
        allowed_hosts_str = config('ALLOWED_HOSTS', cast=str, default='')
        allowed_hosts = [
            host.strip()
            for host in allowed_hosts_str.split(',')
            if host.strip()
        ]
        normalized_hosts = [
            host.lower().split(':', 1)[0] for host in allowed_hosts
        ]
        is_local_dev = any(
            host in {'localhost', '127.0.0.1'} for host in normalized_hosts
        )

        if (
            not debug_mode
            and not is_local_dev
            and not config(
                'REDIS_LOCATION',
                cast=str,
                default='',
            )
        ):
            valid = False
            logger.warning(
                'Production environment variable is not set',
                variable='REDIS_LOCATION',
                hint='Set it to redis://host:port/db',
            )

        return valid
