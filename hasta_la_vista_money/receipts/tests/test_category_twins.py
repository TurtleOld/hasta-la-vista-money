"""Tests for twin-category detection and merge proposals."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock, patch

from django.test import Client, TestCase
from django.urls import reverse

from hasta_la_vista_money.receipts.models import (
    CategoryMergeProposal,
    CategoryMergeProposalStatus,
    Product,
    ProductCategory,
    ProductNameCategoryMapping,
)
from hasta_la_vista_money.receipts.repositories import (
    CategoryMergeProposalRepository,
    ProductCategoryRepository,
    ProductNameCategoryMappingRepository,
    ProductRepository,
)
from hasta_la_vista_money.receipts.services.category_merge_proposal import (
    CategoryMergeProposalService,
)
from hasta_la_vista_money.receipts.services.category_twin_detection import (
    CategoryTwinDetectionService,
)
from hasta_la_vista_money.receipts.tasks import find_category_merge_proposals
from hasta_la_vista_money.users.models import User


class RecordingTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.request: dict[str, Any] | None = None

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        self.request = kwargs
        return self.response


def _pairs_response(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        'choices': [
            {
                'message': {
                    'content': json.dumps(
                        {
                            'pairs': [
                                {'first': first, 'second': second}
                                for first, second in pairs
                            ],
                        },
                    ),
                },
            },
        ],
    }


class CategoryTwinDetectionServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='twin-detection-user',
            password='pass',  # nosec B106: test-only password
            email='twin@example.com',
        )
        self.category_repo = ProductCategoryRepository()
        self.drinks = self.category_repo.get_or_create_category(
            user=self.user,
            name='Газировка',
        )
        self.beverages = self.category_repo.get_or_create_category(
            user=self.user,
            name='Напитки',
        )

    def test_finds_and_resolves_duplicate_pairs(self) -> None:
        transport = RecordingTransport(
            _pairs_response([('Газировка', 'Напитки')]),
        )
        service = CategoryTwinDetectionService(
            transport=transport,
            product_category_repository=self.category_repo,
        )

        pairs = service.find_duplicate_pairs(self.user)

        self.assertEqual(pairs, [(self.drinks, self.beverages)])

    def test_disabled_transport_returns_no_pairs(self) -> None:
        service = CategoryTwinDetectionService(
            transport=None,
            product_category_repository=self.category_repo,
        )

        self.assertFalse(service.enabled)
        self.assertEqual(service.find_duplicate_pairs(self.user), [])

    def test_skips_unknown_and_self_pairs(self) -> None:
        transport = RecordingTransport(
            _pairs_response(
                [
                    ('Газировка', 'Напитки'),
                    ('Газировка', 'Неизвестная'),
                    ('Напитки', 'Напитки'),
                ],
            ),
        )
        service = CategoryTwinDetectionService(
            transport=transport,
            product_category_repository=self.category_repo,
        )

        pairs = service.find_duplicate_pairs(self.user)

        self.assertEqual(pairs, [(self.drinks, self.beverages)])


class CategoryMergeProposalServiceTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='twin-merge-user',
            password='pass',  # nosec B106: test-only password
            email='merge@example.com',
        )
        self.category_repo = ProductCategoryRepository()
        self.service = CategoryMergeProposalService(
            proposal_repository=CategoryMergeProposalRepository(),
            product_category_repository=self.category_repo,
            product_repository=ProductRepository(),
            mapping_repository=ProductNameCategoryMappingRepository(),
        )

    def _category(self, name: str) -> ProductCategory:
        return self.category_repo.get_or_create_category(
            user=self.user,
            name=name,
        )

    def test_creates_pending_proposal(self) -> None:
        a = self._category('Газировка')
        b = self._category('Напитки')

        created = self.service.create_if_absent(
            user=self.user,
            category_a=a,
            category_b=b,
        )

        self.assertTrue(created)
        proposal = CategoryMergeProposal.objects.get(user=self.user)
        self.assertEqual(proposal.status, CategoryMergeProposalStatus.PENDING)
        self.assertEqual(
            {proposal.category_a, proposal.category_b},
            {a, b},
        )

    def test_rejected_pair_is_not_offered_again(self) -> None:
        a = self._category('Газировка')
        b = self._category('Напитки')
        self.service.create_if_absent(
            user=self.user,
            category_a=a,
            category_b=b,
        )
        proposal = CategoryMergeProposal.objects.get(user=self.user)

        self.service.keep(user=self.user, proposal_id=proposal.id)

        self.assertFalse(
            self.service.create_if_absent(
                user=self.user,
                category_a=a,
                category_b=b,
            ),
        )
        self.assertFalse(
            self.service.create_if_absent(
                user=self.user,
                category_a=b,
                category_b=a,
            ),
        )
        self.assertEqual(
            CategoryMergeProposal.objects.filter(user=self.user).count(),
            1,
        )

    def test_merge_moves_products_and_deletes_redundant(self) -> None:
        redundant = self._category('Газировка')
        survivor = self._category('Напитки')
        Product.objects.create(
            user=self.user,
            product_name='Кола',
            category=redundant,
            price=1,
            quantity=1,
            amount=1,
        )
        Product.objects.create(
            user=self.user,
            product_name='Пепси',
            category=survivor,
            price=1,
            quantity=1,
            amount=1,
        )
        Product.objects.create(
            user=self.user,
            product_name='Спрайт',
            category=survivor,
            price=1,
            quantity=1,
            amount=1,
        )
        self.service.create_if_absent(
            user=self.user,
            category_a=redundant,
            category_b=survivor,
        )
        proposal = CategoryMergeProposal.objects.get(user=self.user)

        kept = self.service.merge(user=self.user, proposal_id=proposal.id)

        self.assertEqual(kept, survivor)
        self.assertFalse(
            ProductCategory.objects.filter(pk=redundant.pk).exists(),
        )
        self.assertEqual(
            Product.objects.filter(category=survivor).count(),
            3,
        )
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, CategoryMergeProposalStatus.MERGED)

    def test_merge_repoints_pinned_mappings(self) -> None:
        survivor = self._category('Напитки')
        redundant = self._category('Газировка')
        Product.objects.create(
            user=self.user,
            product_name='Кола',
            category=survivor,
            price=1,
            quantity=1,
            amount=1,
        )
        mapping = ProductNameCategoryMapping.objects.create(
            user=self.user,
            normalized_product_name='кола',
            category=redundant,
        )
        self.service.create_if_absent(
            user=self.user,
            category_a=survivor,
            category_b=redundant,
        )
        proposal = CategoryMergeProposal.objects.get(user=self.user)

        self.service.merge(user=self.user, proposal_id=proposal.id)

        mapping.refresh_from_db()
        self.assertEqual(mapping.category, survivor)
        self.assertFalse(
            ProductCategory.objects.filter(pk=redundant.pk).exists(),
        )

    def test_merge_does_not_happen_without_decision(self) -> None:
        a = self._category('Газировка')
        b = self._category('Напитки')
        Product.objects.create(
            user=self.user,
            product_name='Кола',
            category=a,
            price=1,
            quantity=1,
            amount=1,
        )
        self.service.create_if_absent(
            user=self.user,
            category_a=a,
            category_b=b,
        )

        self.assertTrue(ProductCategory.objects.filter(pk=a.pk).exists())
        self.assertTrue(ProductCategory.objects.filter(pk=b.pk).exists())

    def test_merge_ignores_already_resolved_proposal(self) -> None:
        a = self._category('Газировка')
        b = self._category('Напитки')
        self.service.create_if_absent(
            user=self.user,
            category_a=a,
            category_b=b,
        )
        proposal = CategoryMergeProposal.objects.get(user=self.user)
        self.service.keep(user=self.user, proposal_id=proposal.id)

        result = self.service.merge(user=self.user, proposal_id=proposal.id)

        self.assertIsNone(result)
        self.assertTrue(ProductCategory.objects.filter(pk=a.pk).exists())
        self.assertTrue(ProductCategory.objects.filter(pk=b.pk).exists())


class FindCategoryMergeProposalsTaskTests(TestCase):
    def test_task_creates_proposals_for_detected_pairs(self) -> None:
        user = User.objects.create_user(
            username='twin-task-user',
            password='pass',  # nosec B106: test-only password
            email='task@example.com',
        )
        repo = ProductCategoryRepository()
        a = repo.get_or_create_category(user=user, name='Газировка')
        b = repo.get_or_create_category(user=user, name='Напитки')

        detection = Mock()
        detection.enabled = True
        detection.find_duplicate_pairs.return_value = [(a, b)]
        proposal_service = Mock()
        proposal_service.create_if_absent.return_value = True

        with (
            patch(
                'hasta_la_vista_money.receipts.tasks'
                '._get_category_twin_detection_service',
                return_value=detection,
            ),
            patch(
                'hasta_la_vista_money.receipts.tasks'
                '._get_category_merge_proposal_service',
                return_value=proposal_service,
            ),
        ):
            result = find_category_merge_proposals()

        self.assertEqual(result, {'users': 1, 'proposals': 1})
        proposal_service.create_if_absent.assert_called_once_with(
            user=user,
            category_a=a,
            category_b=b,
        )

    def test_task_skips_when_detection_disabled(self) -> None:
        detection = Mock()
        detection.enabled = False

        with patch(
            'hasta_la_vista_money.receipts.tasks'
            '._get_category_twin_detection_service',
            return_value=detection,
        ):
            result = find_category_merge_proposals()

        self.assertEqual(result, {'users': 0, 'proposals': 0})
        detection.find_duplicate_pairs.assert_not_called()


class CategoryTwinsViewTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='twin-view-user',
            password='pass',  # nosec B106: test-only password
            email='view@example.com',
        )
        repo = ProductCategoryRepository()
        self.a = repo.get_or_create_category(user=self.user, name='Газировка')
        self.b = repo.get_or_create_category(user=self.user, name='Напитки')
        self.proposal = CategoryMergeProposal.objects.create(
            user=self.user,
            category_a=self.a,
            category_b=self.b,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_list_page_shows_proposals(self) -> None:
        response = self.client.get(reverse('receipts:category_twins'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Газировка')
        self.assertContains(response, 'Напитки')

    def test_merge_action_resolves_proposal(self) -> None:
        response = self.client.post(
            reverse(
                'receipts:category_twins_merge',
                kwargs={'pk': self.proposal.pk},
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.proposal.refresh_from_db()
        self.assertEqual(
            self.proposal.status,
            CategoryMergeProposalStatus.MERGED,
        )

    def test_keep_action_resolves_proposal(self) -> None:
        response = self.client.post(
            reverse(
                'receipts:category_twins_keep',
                kwargs={'pk': self.proposal.pk},
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.proposal.refresh_from_db()
        self.assertEqual(
            self.proposal.status,
            CategoryMergeProposalStatus.KEPT,
        )
