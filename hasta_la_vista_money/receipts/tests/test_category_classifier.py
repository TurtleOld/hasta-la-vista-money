"""Tests for the semantic-match (stage 3) product category matching."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from config.containers import ApplicationContainer
from core.services.embedding import (
    EmbeddingServiceError,
    HttpEmbeddingProvider,
    NoopEmbeddingProvider,
)
from hasta_la_vista_money.constants import (
    DEFAULT_PRODUCT_CATEGORY,
    PRODUCT_NAME_EMBEDDING_DIMENSIONS,
)
from hasta_la_vista_money.receipts.models import Product, ProductCategorySource
from hasta_la_vista_money.receipts.repositories import ProductCategoryRepository
from hasta_la_vista_money.receipts.services.category_classifier import (
    ReceiptItemCategoryService,
)
from hasta_la_vista_money.users.models import User


def _vector(seed: int) -> list[float]:
    """Build a deterministic unit vector for cosine-distance assertions."""
    vector = [0.0] * PRODUCT_NAME_EMBEDDING_DIMENSIONS
    vector[seed] = 1.0
    return vector


class _FakeEmbeddingProvider:
    """Test double returning fixed vectors, optionally raising on lookup."""

    def __init__(
        self,
        vectors: dict[str, list[float]] | None = None,
        *,
        unavailable: bool = False,
    ) -> None:
        self._vectors = vectors or {}
        self._unavailable = unavailable
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        if self._unavailable:
            raise EmbeddingServiceError('service down')
        try:
            return self._vectors[text]
        except KeyError as err:
            message = f'no vector for {text!r}'
            raise EmbeddingServiceError(message) from err


class SemanticMatchCategoryTests(TestCase):
    """Third categorization stage: matching by embedding-vector distance."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='semantic-user',
            password='pass',  # nosec B106: test-only password
            email='semantic@example.com',
        )

    def test_finds_category_by_semantic_similarity(self) -> None:
        historic = Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка 900г',
            category=ProductCategoryRepository().get_or_create_category(
                user=self.user,
                name='Завтраки',
            ),
        )
        provider = _FakeEmbeddingProvider(
            {
                'Кефир Здравушка 900г': _vector(0),
                'Kefir Zdravushka pack': _vector(0),
            },
        )
        service = ReceiptItemCategoryService(embedding_provider=provider)

        category = service.categorize(
            user=self.user,
            product_name='Kefir Zdravushka pack',
        )

        self.assertEqual(category, 'Завтраки')
        historic.refresh_from_db()
        self.assertIsNotNone(historic.name_embedding)

    def test_reports_semantic_match_source(self) -> None:
        Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка 900г',
            category=ProductCategoryRepository().get_or_create_category(
                user=self.user,
                name='Завтраки',
            ),
        )
        provider = _FakeEmbeddingProvider(
            {
                'Кефир Здравушка 900г': _vector(0),
                'Kefir Zdravushka pack': _vector(0),
            },
        )
        service = ReceiptItemCategoryService(embedding_provider=provider)

        items = service.categorize_items(
            user=self.user,
            items=[{'product_name': 'Kefir Zdravushka pack'}],
        )

        self.assertEqual(
            items[0]['category_source'],
            ProductCategorySource.SEMANTIC_MATCH,
        )

    def test_respects_configured_threshold(self) -> None:
        Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка 900г',
            category=ProductCategoryRepository().get_or_create_category(
                user=self.user,
                name='Завтраки',
            ),
        )
        provider = _FakeEmbeddingProvider(
            {
                'Кефир Здравушка 900г': _vector(0),
                'Совершенно другой товар': _vector(1),
            },
        )
        service = ReceiptItemCategoryService(embedding_provider=provider)

        category = service.categorize(
            user=self.user,
            product_name='Совершенно другой товар',
        )

        self.assertEqual(category, DEFAULT_PRODUCT_CATEGORY)

    @override_settings(RECEIPT_CATEGORY_SEMANTIC_SIMILARITY_THRESHOLD=0.0)
    def test_lenient_threshold_still_finds_category(self) -> None:
        Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка 900г',
            category=ProductCategoryRepository().get_or_create_category(
                user=self.user,
                name='Завтраки',
            ),
        )
        provider = _FakeEmbeddingProvider(
            {
                'Кефир Здравушка 900г': _vector(0),
                'Совершенно другой товар': _vector(1),
            },
        )
        service = ReceiptItemCategoryService(embedding_provider=provider)

        category = service.categorize(
            user=self.user,
            product_name='Совершенно другой товар',
        )

        self.assertEqual(category, 'Завтраки')

    def test_embedding_service_unavailable_does_not_block_categorization(
        self,
    ) -> None:
        provider = _FakeEmbeddingProvider(unavailable=True)
        service = ReceiptItemCategoryService(embedding_provider=provider)

        category = service.categorize(
            user=self.user,
            product_name='Что угодно',
        )

        self.assertEqual(category, DEFAULT_PRODUCT_CATEGORY)

    def test_stored_embedding_is_reused_not_recomputed(self) -> None:
        historic = Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка 900г',
            category=ProductCategoryRepository().get_or_create_category(
                user=self.user,
                name='Завтраки',
            ),
            name_embedding=_vector(0),
        )
        provider = _FakeEmbeddingProvider({'Kefir Zdravushka pack': _vector(0)})
        service = ReceiptItemCategoryService(embedding_provider=provider)

        category = service.categorize(
            user=self.user,
            product_name='Kefir Zdravushka pack',
        )

        self.assertEqual(category, 'Завтраки')
        self.assertNotIn(historic.product_name, provider.calls)

    def test_semantic_stage_is_skipped_when_writing_match_already_won(
        self,
    ) -> None:
        Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category=ProductCategoryRepository().get_or_create_category(
                user=self.user,
                name='Завтраки',
            ),
        )
        provider = MagicMock()
        service = ReceiptItemCategoryService(embedding_provider=provider)

        category = service.categorize(
            user=self.user,
            product_name='кефир здравушка',
        )

        self.assertEqual(category, 'Завтраки')
        provider.embed.assert_not_called()


class NoopEmbeddingProviderTests(TestCase):
    def test_always_raises(self) -> None:
        provider = NoopEmbeddingProvider()
        with self.assertRaises(EmbeddingServiceError):
            provider.embed('что угодно')


class HttpEmbeddingProviderTests(TestCase):
    def _make_provider(self) -> HttpEmbeddingProvider:
        return HttpEmbeddingProvider(
            base_url='http://localhost:8080/v1',
            api_key='',
            model='multilingual-e5-small',
        )

    def test_returns_embedding_from_response(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': [{'embedding': [0.1, 0.2, 0.3]}],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response

        with patch('core.services.embedding.httpx.Client') as mock_client_cls:
            mock_client_cls.return_value.__enter__ = MagicMock(
                return_value=mock_client,
            )
            mock_client_cls.return_value.__exit__ = MagicMock(
                return_value=False,
            )
            provider = self._make_provider()
            result = provider.embed('Кефир')

        self.assertEqual(result, [0.1, 0.2, 0.3])

    def test_raises_embedding_service_error_on_failure(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception('connection refused')

        with patch('core.services.embedding.httpx.Client') as mock_client_cls:
            mock_client_cls.return_value.__enter__ = MagicMock(
                return_value=mock_client,
            )
            mock_client_cls.return_value.__exit__ = MagicMock(
                return_value=False,
            )
            provider = self._make_provider()
            with self.assertRaises(EmbeddingServiceError):
                provider.embed('Кефир')


@override_settings(
    RECEIPT_CATEGORY_EMBEDDING_BASE_URL='http://localhost:8080/v1',
    RECEIPT_CATEGORY_EMBEDDING_API_KEY='key',
    RECEIPT_CATEGORY_EMBEDDING_MODEL='multilingual-e5-small',
)
class EmbeddingProviderContainerTests(TestCase):
    def test_container_builds_http_provider_when_configured(self) -> None:
        container = ApplicationContainer()

        self.assertIsInstance(
            container.receipts.embedding_provider(),
            HttpEmbeddingProvider,
        )

    def test_container_builds_noop_provider_when_not_configured(self) -> None:
        with self.settings(RECEIPT_CATEGORY_EMBEDDING_BASE_URL=''):
            container = ApplicationContainer()

            self.assertIsInstance(
                container.receipts.embedding_provider(),
                NoopEmbeddingProvider,
            )
