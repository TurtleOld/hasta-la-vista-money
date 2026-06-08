"""Tests for finance account repositories."""

from unittest import mock

from django.test import SimpleTestCase

from hasta_la_vista_money.finance_account.models import TransferMoneyLog
from hasta_la_vista_money.finance_account.repositories import (
    TransferMoneyLogRepository,
)


class TestTransferMoneyLogRepository(SimpleTestCase):
    """Test cases for transfer money log repository."""

    def test_get_by_id_for_user_locks_only_transfer_row(self) -> None:
        """FOR UPDATE should not lock nullable joined account rows."""
        repository = TransferMoneyLogRepository()
        user = mock.Mock()
        selected_queryset = mock.Mock()
        locked_queryset = mock.Mock()
        transfer_log = mock.Mock()
        selected_queryset.select_for_update.return_value = locked_queryset
        locked_queryset.get.return_value = transfer_log

        with mock.patch.object(
            TransferMoneyLog.objects,
            'select_related',
            return_value=selected_queryset,
        ) as select_related:
            result = repository.get_by_id_for_user(
                9,
                user,
                for_update=True,
            )

        select_related.assert_called_once_with(
            'from_account',
            'to_account',
            'user',
        )
        selected_queryset.select_for_update.assert_called_once_with(
            of=('self',),
        )
        locked_queryset.get.assert_called_once_with(pk=9, user=user)
        self.assertEqual(result, transfer_log)
