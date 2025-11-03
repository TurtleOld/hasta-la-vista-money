from os import environ

from decouple import config
from icecream import ic


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
            ic('SECRET_KEY is not set, use make secretkey to generate it')
        if not config('ALLOWED_HOSTS', cast=str, default=''):
            valid = False
            ic(
                'ALLOWED_HOSTS is not set, set it to a '
                'comma-separated list of hosts',
            )
        if not config('DATABASE_URL', cast=str, default=''):
            valid = False
            ic('DATABASE_URL is not set, set it to a valid database URL')

        debug_mode = config('DEBUG', default=False, cast=bool)
        if not debug_mode and not config(
            'REDIS_LOCATION',
            cast=str,
            default='',
        ):
            valid = False
            ic(
                'REDIS_LOCATION is not set for production, set it to redis://host:port/db',
            )

        return valid
