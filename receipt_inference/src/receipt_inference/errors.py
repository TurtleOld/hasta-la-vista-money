"""Domain errors for the receipt inference service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReceiptInferenceError(Exception):
    """Structured service error for HTTP mapping."""

    error_code: str
    message: str
    status_code: int

    def __str__(self) -> str:
        return self.message
