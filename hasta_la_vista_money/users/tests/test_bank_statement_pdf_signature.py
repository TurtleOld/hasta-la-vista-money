from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from hasta_la_vista_money.constants import ACCOUNT_TYPE_DEBIT_CARD
from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.forms import BankStatementUploadForm
from hasta_la_vista_money.users.models import User


class BankStatementPdfSignatureTest(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='pdf-user', password='x')
        self.account = Account.objects.create(
            user=self.user,
            name_account='Debit',
            balance=0,
            currency='RUB',
            type_account=ACCOUNT_TYPE_DEBIT_CARD,
        )

    def _form(self, content: bytes) -> BankStatementUploadForm:
        return BankStatementUploadForm(
            self.user,
            {'account': self.account.pk},
            {'pdf_file': SimpleUploadedFile('statement.pdf', content)},
        )

    def test_file_without_pdf_signature_is_rejected(self) -> None:
        form = self._form(b'MZ\x90\x00 not a pdf')
        self.assertFalse(form.is_valid())
        self.assertIn('pdf_file', form.errors)

    def test_file_with_pdf_signature_is_accepted(self) -> None:
        form = self._form(b'%PDF-1.4 content')
        self.assertTrue(form.is_valid(), form.errors)
