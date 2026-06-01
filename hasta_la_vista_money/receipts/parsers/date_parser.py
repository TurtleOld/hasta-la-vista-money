from datetime import datetime
from typing import Any, ClassVar, Final

from django.utils import timezone

RECEIPT_DATE_OUTPUT_FORMAT: Final = '%d.%m.%Y %H:%M'


class ReceiptDateParseError(ValueError):
    pass


class ReceiptDateParser:
    input_formats: ClassVar[tuple[str, ...]] = (
        RECEIPT_DATE_OUTPUT_FORMAT,
        '%d.%m.%y %H:%M',
    )

    @classmethod
    def parse(cls, value: Any) -> datetime:
        if isinstance(value, datetime):
            if timezone.is_naive(value):
                return timezone.make_aware(
                    value,
                    timezone.get_current_timezone(),
                )
            return value.astimezone(timezone.get_current_timezone())

        text = str(value).strip() if value is not None else ''
        if not text:
            raise ReceiptDateParseError('receipt date is empty')

        for date_format in cls.input_formats:
            try:
                parsed = datetime.strptime(text, date_format).replace(
                    tzinfo=timezone.get_current_timezone(),
                )
            except ValueError:
                continue
            return parsed

        raise ReceiptDateParseError('receipt date has unsupported format')

    @classmethod
    def normalize(cls, value: Any) -> str:
        return cls.parse(value).strftime(RECEIPT_DATE_OUTPUT_FORMAT)
