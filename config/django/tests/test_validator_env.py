from unittest.mock import patch

from django.test import SimpleTestCase

from config.django.validator_env import EnvironmentValidator


class EnvironmentValidatorTest(SimpleTestCase):
    def test_validate_returns_true_for_ci_environment(self) -> None:
        with patch.dict(
            'config.django.validator_env.environ', {'CI': '1'}, clear=True
        ):
            validator = EnvironmentValidator()
            self.assertTrue(validator.validate())

    def test_validate_returns_false_when_variables_missing(self) -> None:
        def fake_config(key: str, cast=str, default=''):
            values: dict[str, object] = {
                'SECRET_KEY': '',
                'ALLOWED_HOSTS': '',
                'DATABASE_URL': '',
                'DEBUG': False,
                'REDIS_LOCATION': '',
            }
            _ = cast
            return values.get(key, default)

        with (
            patch.dict('config.django.validator_env.environ', {}, clear=True),
            patch(
                'config.django.validator_env.config', side_effect=fake_config
            ),
            patch('config.django.validator_env.ic') as mock_ic,
        ):
            validator = EnvironmentValidator()
            self.assertFalse(validator.validate())
            self.assertGreaterEqual(mock_ic.call_count, 4)

    def test_validate_returns_true_with_complete_configuration(self) -> None:
        def fake_config(key: str, cast=str, default=''):
            values: dict[str, object] = {
                'SECRET_KEY': 'secret',
                'ALLOWED_HOSTS': 'localhost',
                'DATABASE_URL': 'sqlite://:memory:',
                'DEBUG': False,
                'REDIS_LOCATION': 'redis://localhost:6379/0',
            }
            _ = cast
            return values.get(key, default)

        with (
            patch.dict('config.django.validator_env.environ', {}, clear=True),
            patch(
                'config.django.validator_env.config', side_effect=fake_config
            ),
            patch('config.django.validator_env.ic'),
        ):
            validator = EnvironmentValidator()
            self.assertTrue(validator.validate())
