"""Statistics stays available with a concrete completeness warning."""

from django.test import Client, TestCase
from django.urls import reverse

from hasta_la_vista_money.finance_account.models import Account
from hasta_la_vista_money.users.models import (
    BankStatementRow,
    BankStatementUpload,
    User,
)


class StatisticsCompletenessWarningTest(TestCase):
    """The statistics screen names the account and the concrete reason."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='statistics-completeness',
            password='test-only-password',  # nosec B106
        )
        self.account = Account.objects.create(
            user=self.user,
            name_account='Счёт без доказательств',
            currency='RUB',
        )
        self.upload = BankStatementUpload.objects.create(
            user=self.user,
            account=self.account,
            pdf_file='legacy.pdf',
            status=BankStatementUpload.Status.COMPLETED,
        )
        BankStatementRow.objects.create(
            upload=self.upload,
            decision=BankStatementRow.Decision.DEFERRED,
            amount=None,
            transaction_date=None,
            date_precision=BankStatementRow.DatePrecision.UNKNOWN,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_statistics_show_concrete_warning_not_percentage(self):
        response = self.client.get(reverse('users:statistics'))

        self.assertEqual(response.status_code, 200)
        alerts = response.context['statistics_alerts']
        completeness_alerts = [
            alert for alert in alerts if alert['title'] == 'Контроль учёта'
        ]
        self.assertTrue(completeness_alerts)
        messages = ' '.join(
            str(alert['message']) for alert in completeness_alerts
        )
        self.assertIn(self.account.name_account, messages)
        self.assertNotIn('%', messages)

    def test_statistics_remain_available_without_accounts(self):
        self.user.finance_account_users.all().delete()

        response = self.client.get(reverse('users:statistics'))

        self.assertEqual(response.status_code, 200)
