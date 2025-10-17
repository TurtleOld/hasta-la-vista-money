from os import environ
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

        if not environ.get('SECRET_KEY'):
            valid = False
            ic('SECRET_KEY is not set, use make secretkey to generate it')
        if not environ.get('DEBUG'):
            valid = False
            ic('DEBUG is not set, set it to true or false')
        if not environ.get('ALLOWED_HOSTS'):
            valid = False
            ic('ALLOWED_HOSTS is not set, set it to a comma-separated list of hosts')
        if not environ.get('DATABASE_URL'):
            valid = False
            ic('DATABASE_URL is not set, set it to a valid database URL')
        return valid
