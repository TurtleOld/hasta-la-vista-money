"""Type definitions and aliases for common types.

This module provides type aliases and TypedDict definitions to improve
code readability and type safety.
"""

from datetime import date, datetime
from decimal import Decimal

type AccountBalance = Decimal
type TransactionAmount = Decimal
type DateOrDateTime = date | datetime
