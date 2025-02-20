from django.test import TestCase
from django.urls import reverse_lazy
from hasta_la_vista_money import constants
from hasta_la_vista_money.loan.models import Loan
from hasta_la_vista_money.users.models import User


class TestLoan(TestCase):
    fixtures = [
        'users.yaml',
        'finance_account.yaml',
        'income.yaml',
        'income_cat.yaml',
        'loan.yaml',
    ]

    def setUp(self) -> None:
        self.user = User.objects.get(pk=1)
        self.loan1 = Loan.objects.get(pk=2)
        self.loan2 = Loan.objects.get(pk=3)

    def test_list_loan(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(reverse_lazy('loan:list'))
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)

    def test_create_annuity_loan(self):
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = {
            'type_loan': 'Annuity',
            'date': '2023-10-01',
            'loan_amount': 10000,
            'annual_interest_rate': 5,
            'period_loan': 12,
        }
        response = self.client.post(url, data, follow=True)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
        self.assertTrue(Loan.objects.filter(loan_amount=10000).exists())

    def test_create_differentiated_loan(self):
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = {
            'type_loan': 'Differentiated',
            'date': '2023-10-01',
            'loan_amount': 10000,
            'annual_interest_rate': 5,
            'period_loan': 12,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.REDIRECTS)
        self.assertTrue(Loan.objects.filter(loan_amount=10000).exists())

    def test_create_loan_invalid_data(self):
        self.client.force_login(self.user)
        url = reverse_lazy('loan:create')
        data = {
            'type_loan': 'Annuity',
            'date': '',
            'loan_amount': 10000,
            'annual_interest_rate': 5,
            'period_loan': 12,
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, constants.SUCCESS_CODE)
