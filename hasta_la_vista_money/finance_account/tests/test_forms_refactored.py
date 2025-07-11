"""
Tests for refactored finance account forms.

Tests cover the new form structure with base classes, validators, and services.
"""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from hasta_la_vista_money.finance_account.forms import (
    AddAccountForm,
    TransferMoneyAccountForm,
)
from hasta_la_vista_money.finance_account.models import Account, TransferMoneyLog
from hasta_la_vista_money.finance_account.validators import (
    validate_account_balance,
    validate_different_accounts,
    validate_credit_fields_required,
    validate_positive_amount,
)
from hasta_la_vista_money.users.models import User


