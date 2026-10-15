import re

from django.test import SimpleTestCase

from hasta_la_vista_money.core.upload_paths import (
    bank_statement_upload_to,
    receipt_processing_upload_to,
)


class UploadPathsTest(SimpleTestCase):
    def test_bank_statement_name_is_random(self) -> None:
        first = bank_statement_upload_to(None, 'Statement Ivanov.PDF')
        second = bank_statement_upload_to(None, 'Statement Ivanov.PDF')
        self.assertRegex(first, r'^bank_statements/[0-9a-f]{32}\.pdf$')
        self.assertNotEqual(first, second)
        self.assertNotIn('Ivanov', first)

    def test_receipt_processing_name_is_random(self) -> None:
        path = receipt_processing_upload_to(None, 'photo.jpg')
        self.assertIsNotNone(
            re.match(r'^receipt_processing_logs/[0-9a-f]{32}\.jpg$', path),
        )
