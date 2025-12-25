"""Bank constants for credit card calculations."""

from typing import Final

BANK_SBERBANK: Final = 'SBERBANK'
BANK_RAIFFEISENBANK: Final = 'RAIFFAISENBANK'
BANK_DEFAULT: Final = '-'

SUPPORTED_BANKS: Final[tuple[str, ...]] = (
    BANK_SBERBANK,
    BANK_RAIFFEISENBANK,
)
