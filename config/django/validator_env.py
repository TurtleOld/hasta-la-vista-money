from decouple import config


class EnvironmentValidator:
    def __init__(self, env_file: str):
        self.env_file = env_file

    def validate(self) -> bool:
        if config("GITHUB_WORKFLOW"):
            return True

        valid = True
        with open(self.env_file, 'r') as file:
            for line in file:
                line = line.strip()
                if line.startswith('#') or not line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                if not key or not value:
                    continue
                if key == 'SECRET_KEY':
                    if len(value) < 50:
                        valid = False
                        print('SECRET_KEY must be at least 50 characters long')
                if key == 'DEBUG':
                    if value.lower() not in ['true', 'false']:
                        valid = False
                        print('DEBUG must be true or false (case insensitive)')
                if key == 'ALLOWED_HOSTS':
                    if not any(
                        True
                        for val in value.split(',')
                        if not val.startswith('http') or not val.startswith('https')
                    ):
                        valid = False
                        print('ALLOWED_HOSTS must start with http or https')
                if key == 'DATABASE_URL':
                    if not value.startswith('postgres'):
                        valid = False
                        print('DATABASE_URL must start with postgres')
        return valid
