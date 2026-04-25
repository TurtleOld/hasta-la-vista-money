from unittest.mock import patch

from django.test import SimpleTestCase

from config.django.validator_env import EnvironmentValidator


class EnvironmentValidatorTest(SimpleTestCase):
    def test_validate_returns_true_for_ci_environment(self) -> None:
        with patch.dict(
            'config.django.validator_env.environ',
            {'CI': '1'},
            clear=True,
        ):
            validator = EnvironmentValidator()
            self.assertTrue(validator.validate())

    def test_validate_returns_false_when_variables_missing(self) -> None:
        def fake_config(
            key: str,
            cast: type[str] | type[bool] = str,
            default: str = '',
        ) -> str | bool:
            values: dict[str, object] = {
                'SECRET_KEY': '',
                'ALLOWED_HOSTS': '',
                'DATABASE_URL': '',
                'DEBUG': False,
                'REDIS_LOCATION': '',
            }
            _ = cast
            result = values.get(key, default)
            return cast(result) if result is not None else default

        with (
            patch.dict('config.django.validator_env.environ', {}, clear=True),
            patch(
                'config.django.validator_env.config',
                side_effect=fake_config,
            ),
            patch('config.django.validator_env.logger.warning') as mock_warning,
        ):
            validator = EnvironmentValidator()
            self.assertFalse(validator.validate())
            self.assertGreaterEqual(mock_warning.call_count, 4)

    def test_validate_returns_true_with_complete_configuration(self) -> None:
        def fake_config(
            key: str,
            cast: type[str] | type[bool] = str,
            default: str = '',
        ) -> str | bool:
            values: dict[str, object] = {
                'SECRET_KEY': 'secret',
                'ALLOWED_HOSTS': 'localhost',
                'DATABASE_URL': 'sqlite://:memory:',
                'DEBUG': False,
                'REDIS_LOCATION': 'redis://localhost:6379/0',
            }
            _ = cast
            result = values.get(key, default)
            return cast(result) if result is not None else default

        with (
            patch.dict('config.django.validator_env.environ', {}, clear=True),
            patch(
                'config.django.validator_env.config',
                side_effect=fake_config,
            ),
            patch('config.django.validator_env.logger.warning'),
        ):
            validator = EnvironmentValidator()
            self.assertTrue(validator.validate())
