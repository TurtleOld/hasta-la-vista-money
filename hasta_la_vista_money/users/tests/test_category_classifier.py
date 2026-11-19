from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from config.containers import ApplicationContainer
from core.services.external_model import ExternalModelTransport
from hasta_la_vista_money.users.services.category_classifier import (
    ExternalModelCategoryClassifier,
    LocalCategoryClassifier,
    NoopClassifier,
)


class TestNoopClassifier(TestCase):
    def test_returns_description_unchanged(self):
        clf = NoopClassifier()
        result = clf.classify(
            description='MAGNIT',
            transaction_type='expense',
            existing_categories=['Продукты', 'Транспорт'],
        )
        self.assertEqual(result, 'MAGNIT')

    def test_returns_description_when_no_categories(self):
        clf = NoopClassifier()
        result = clf.classify('ЗП', 'income', [])
        self.assertEqual(result, 'ЗП')


class TestExternalModelCategoryClassifier(TestCase):
    def _make_clf(self):
        return ExternalModelCategoryClassifier(
            transport=ExternalModelTransport(
                base_url='http://localhost:1234/v1',
                api_key='',
                model='llama3',
            ),
        )

    @patch(
        'core.services.external_model.httpx.Client',
    )
    def test_returns_category_from_llm(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'choices': [{'message': {'content': 'Продукты'}}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=mock_client,
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        clf = self._make_clf()
        result = clf.classify('MAGNIT', 'expense', ['Продукты', 'Транспорт'])
        self.assertEqual(result, 'Продукты')

    @patch(
        'core.services.external_model.httpx.Client',
    )
    def test_falls_back_to_description_on_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception('connection refused')
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=mock_client,
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        clf = self._make_clf()
        result = clf.classify('NETFLIX.COM', 'expense', [])
        self.assertEqual(result, 'NETFLIX.COM')

    @patch(
        'core.services.external_model.httpx.Client',
    )
    def test_strips_whitespace_from_llm_response(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'choices': [{'message': {'content': '  Транспорт  '}}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value.__enter__ = MagicMock(
            return_value=mock_client,
        )
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        clf = self._make_clf()
        result = clf.classify('Яндекс Такси', 'expense', ['Транспорт'])
        self.assertEqual(result, 'Транспорт')


class TestLocalCategoryClassifier(TestCase):
    def setUp(self) -> None:
        self.classifier = LocalCategoryClassifier()

    def test_matches_existing_category_by_name(self) -> None:
        result = self.classifier.classify(
            'Оплата в магазине Продукты у дома',
            'expense',
            ['Транспорт', 'Продукты'],
        )

        self.assertEqual(result, 'Продукты')

    def test_matches_case_insensitively(self) -> None:
        result = self.classifier.classify(
            'magnit supermarket',
            'expense',
            ['MAGNIT'],
        )

        self.assertEqual(result, 'MAGNIT')

    def test_unknown_category_returns_fallback(self) -> None:
        result = self.classifier.classify(
            'Неизвестный получатель',
            'expense',
            ['Продукты', 'Транспорт'],
        )

        self.assertEqual(result, 'Без категории')

    def test_empty_description_returns_fallback(self) -> None:
        result = self.classifier.classify('   ', 'income', ['Зарплата'])

        self.assertEqual(result, 'Без категории')

    @patch(
        'core.services.external_model.httpx.Client',
    )
    def test_never_calls_a_network_model(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        self.classifier.classify('Магазин', 'expense', ['Продукты'])

        mock_client_cls.assert_not_called()


@override_settings(
    RECEIPT_CATEGORY_MODEL_BASE_URL='http://localhost:1234/v1',
    RECEIPT_CATEGORY_MODEL_API_KEY='receipt-key',
    RECEIPT_CATEGORY_MODEL_NAME='receipt-model',
)
class TestBankStatementClassifierIsLocal(TestCase):
    def test_bank_statement_classifier_is_local(self) -> None:
        container = ApplicationContainer()

        self.assertIsInstance(
            container.users.category_classifier(),
            LocalCategoryClassifier,
        )

    def test_bank_statement_model_settings_never_enable_network(self) -> None:
        with self.settings(
            BANK_STATEMENT_CATEGORY_MODEL_BASE_URL=('http://localhost:1234/v1'),
            BANK_STATEMENT_CATEGORY_MODEL_API_KEY='bank-key',
            BANK_STATEMENT_CATEGORY_MODEL_NAME='bank-model',
            CATEGORY_CLASSIFIER_BASE_URL='http://localhost:1234/v1',
            CATEGORY_CLASSIFIER_API_KEY='legacy-key',
            CATEGORY_CLASSIFIER_MODEL='legacy-model',
        ):
            container = ApplicationContainer()

            self.assertIsInstance(
                container.users.category_classifier(),
                LocalCategoryClassifier,
            )
