"""Tests for the per-stage category-matching hit-rate measurement."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from hasta_la_vista_money.receipts.models import (
    Product,
    ProductNameCategoryMapping,
)
from hasta_la_vista_money.receipts.repositories import (
    ProductCategoryRepository,
)
from hasta_la_vista_money.receipts.services import category_matching_evaluation
from hasta_la_vista_money.users.models import User

from .test_category_classifier import _FakeEmbeddingProvider, _vector


class EvaluateCategoryMatchingStagesTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='eval-user',
            password='pass',  # nosec B106: test-only password
            email='eval@example.com',
        )
        self.category_repo = ProductCategoryRepository()

    def test_pinned_stage_counts_only_applicable_rows(self) -> None:
        category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Завтраки',
        )
        product = Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category=category,
        )
        ProductNameCategoryMapping.objects.create(
            user=self.user,
            normalized_product_name='кефир здравушка',
            category=category,
        )

        results = (
            category_matching_evaluation.evaluate_category_matching_stages(
                users=User.objects.filter(pk=self.user.pk),
                embedding_provider=_FakeEmbeddingProvider(
                    {product.product_name: _vector(0)},
                ),
            )
        )

        pinned = next(r for r in results if r.stage == 'pinned_name_match')
        self.assertEqual((pinned.hits, pinned.total), (1, 1))

    def test_writing_stage_reports_wrong_prediction_as_a_miss(self) -> None:
        drinks = self.category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )
        breakfast = self.category_repo.get_or_create_category(
            user=self.user,
            name='Завтраки',
        )
        Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category=drinks,
        )
        target = Product.objects.create(
            user=self.user,
            product_name='кефир здравушка',
            category=breakfast,
        )

        results = (
            category_matching_evaluation.evaluate_category_matching_stages(
                users=User.objects.filter(pk=self.user.pk),
                embedding_provider=_FakeEmbeddingProvider(
                    {target.product_name: _vector(0)},
                ),
            )
        )

        writing = next(r for r in results if r.stage == 'writing_match')
        self.assertEqual(writing.total, 2)
        self.assertEqual(writing.hits, 0)

    def test_semantic_stage_matches_by_embedding_distance(self) -> None:
        category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Завтраки',
        )
        Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка 900г',
            category=category,
        )
        target = Product.objects.create(
            user=self.user,
            product_name='Kefir Zdravushka pack',
            category=category,
        )

        results = (
            category_matching_evaluation.evaluate_category_matching_stages(
                users=User.objects.filter(pk=self.user.pk),
                embedding_provider=_FakeEmbeddingProvider(
                    {
                        'Кефир Здравушка 900г': _vector(0),
                        target.product_name: _vector(0),
                    },
                ),
            )
        )

        semantic = next(r for r in results if r.stage == 'semantic_match')
        self.assertEqual((semantic.hits, semantic.total), (1, 1))

    def test_command_prints_hit_rate_per_stage(self) -> None:
        category = self.category_repo.get_or_create_category(
            user=self.user,
            name='Завтраки',
        )
        Product.objects.create(
            user=self.user,
            product_name='Кефир Здравушка',
            category=category,
        )
        ProductNameCategoryMapping.objects.create(
            user=self.user,
            normalized_product_name='кефир здравушка',
            category=category,
        )

        out = StringIO()
        call_command(
            'evaluate_category_matching',
            f'--user-id={self.user.pk}',
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn('pinned_name_match:', output)
        self.assertIn('writing_match:', output)
        self.assertIn('semantic_match:', output)
