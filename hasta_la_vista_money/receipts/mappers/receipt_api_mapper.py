"""Mapper for converting receipts API request data to DTOs."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from hasta_la_vista_money.receipts.services.receipt_creator import (
    ReceiptCreateData,
    SellerCreateData,
)


class ReceiptAPIDataMapper:
    """Mapper for converting receipts API request data to service DTOs.

    Converts raw API request data into structured DTOs for use with services.
    """

    def map_request_to_receipt_data(
        self,
        request_data: dict[str, Any],
    ) -> ReceiptCreateData:
        """Map API request data to ReceiptCreateData DTO.

        Args:
            request_data: Raw API request data

        Returns:
            ReceiptCreateData DTO with receipt information
        """
        return ReceiptCreateData(
            receipt_date=self.parse_receipt_date(
                request_data.get('receipt_date'),
            ),
            total_sum=self.get_decimal(request_data['total_sum']),
            number_receipt=request_data.get('number_receipt'),
            operation_type=request_data.get('operation_type'),
            nds10=self.get_optional_decimal(request_data.get('nds10')),
            nds20=self.get_optional_decimal(request_data.get('nds20')),
        )

    def map_request_to_seller_data(
        self,
        request_data: dict[str, Any],
    ) -> SellerCreateData:
        """Map API request data to SellerCreateData DTO.

        Args:
            request_data: Raw API request data

        Returns:
            SellerCreateData DTO with seller information
        """
        seller_data = request_data.get('seller') or {}
        return SellerCreateData(
            name_seller=str(seller_data.get('name_seller', '')),
            retail_place_address=seller_data.get('retail_place_address'),
            retail_place=seller_data.get('retail_place'),
        )

    def parse_receipt_date(self, raw_date: Any) -> datetime:
        """Parse receipt date from various formats.

        Args:
            raw_date: Date in string, datetime, or other format

        Returns:
            Parsed datetime object, defaults to current time if parsing fails
        """
        if isinstance(raw_date, str):
            try:
                return datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # Fallback to current time if parsing fails
                return datetime.now(ZoneInfo('UTC'))
        if isinstance(raw_date, datetime):
            return raw_date
        # Default to current time if type is unknown
        return datetime.now(ZoneInfo('UTC'))

    def get_decimal(self, value: Any) -> Decimal:
        """Convert value to Decimal.

        Args:
            value: Value to convert (can be string, int, float, Decimal)

        Returns:
            Decimal representation of value

        Raises:
            ValueError: If value cannot be converted to Decimal
        """
        return Decimal(str(value))

    def get_optional_decimal(self, value: Any) -> Decimal | None:
        """Convert value to Decimal or None.

        Args:
            value: Value to convert (can be string, int, float, Decimal, None)

        Returns:
            Decimal representation of value or None if value is None
        """
        if value is None:
            return None
        return self.get_decimal(value)

