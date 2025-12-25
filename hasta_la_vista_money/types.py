"""Type definitions and aliases for common types used throughout the application.

This module provides type aliases and TypedDict definitions to improve
code readability and type safety.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import TypeAlias

AccountBalance: TypeAlias = Decimal
TransactionAmount: TypeAlias = Decimal
DateOrDateTime: TypeAlias = date | datetime

