"""Bank constants and choices for finance accounts."""

from typing import Final

from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

BANK_SBERBANK: Final = 'SBERBANK'
BANK_RAIFFEISENBANK: Final = 'RAIFFAISENBANK'
BANK_DEFAULT: Final = '-'

BANK_CHOICES: Final[tuple[tuple[str, str | Promise], ...]] = (
    (BANK_DEFAULT, _('—')),
    (BANK_SBERBANK, _('Сбербанк')),
    (BANK_RAIFFEISENBANK, _('Райффайзенбанк')),
)

SUPPORTED_BANKS: Final[tuple[str, ...]] = (
    BANK_SBERBANK,
    BANK_RAIFFEISENBANK,
)
