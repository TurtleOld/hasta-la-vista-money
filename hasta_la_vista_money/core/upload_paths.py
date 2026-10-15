"""Upload path callables that replace user-supplied file names."""

import uuid
from pathlib import Path
from typing import Any

from hasta_la_vista_money.constants import (
    BANK_STATEMENT_UPLOAD_DIR,
    RECEIPT_PROCESSING_UPLOAD_DIR,
)


def _random_name(prefix: str, filename: str) -> str:
    extension = Path(filename).suffix.lower()
    return f'{prefix}/{uuid.uuid4().hex}{extension}'


def bank_statement_upload_to(instance: Any, filename: str) -> str:
    del instance
    return _random_name(BANK_STATEMENT_UPLOAD_DIR, filename)


def receipt_processing_upload_to(instance: Any, filename: str) -> str:
    del instance
    return _random_name(RECEIPT_PROCESSING_UPLOAD_DIR, filename)
