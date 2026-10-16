import importlib
from typing import Any

import structlog
from django.conf import settings
from django.test import SimpleTestCase

APP_LOGGER = 'hasta_la_vista_money'


class ApplicationLoggingConfigTest(SimpleTestCase):
    def test_app_logger_is_configured(self) -> None:
        logging_config: Any = settings.LOGGING
        logger_config = logging_config['loggers'][APP_LOGGER]

        self.assertIn('console', logger_config['handlers'])
        self.assertFalse(logger_config['propagate'])
        self.assertEqual(logger_config['level'], settings.LOG_LEVEL)

    def test_app_structlog_event_reaches_stdlib_logger(self) -> None:
        name = f'{APP_LOGGER}.users.services.bank_statement_import'

        with self.assertLogs(name, 'INFO') as captured:
            structlog.get_logger(name).info(
                'bank_statement_import_started',
                upload_id=1,
                user_id=2,
            )

        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertIn('bank_statement_import_started', message)
        self.assertIn('upload_id', message)

    def test_prod_settings_configure_app_logger(self) -> None:
        prod: Any = importlib.import_module('config.django.prod')
        loggers = prod.LOGGING['loggers']

        self.assertIn(APP_LOGGER, loggers)
        self.assertNotIn('myproject', loggers)
        self.assertEqual(
            loggers[APP_LOGGER]['handlers'],
            ['json_file', 'console'],
        )
        self.assertFalse(loggers[APP_LOGGER]['propagate'])
