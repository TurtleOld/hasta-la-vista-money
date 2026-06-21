from unittest.mock import MagicMock, patch

from django.test import TestCase

from hasta_la_vista_money.users.services.category_classifier import (
    NoopClassifier,
    OpenAICompatibleClassifier,
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


class TestOpenAICompatibleClassifier(TestCase):
    def _make_clf(self):
        return OpenAICompatibleClassifier(
            base_url='http://localhost:1234/v1',
            api_key='',
            model='llama3',
        )

    @patch(
        'hasta_la_vista_money.users.services.category_classifier.httpx.Client',
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
        'hasta_la_vista_money.users.services.category_classifier.httpx.Client',
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
        'hasta_la_vista_money.users.services.category_classifier.httpx.Client',
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
