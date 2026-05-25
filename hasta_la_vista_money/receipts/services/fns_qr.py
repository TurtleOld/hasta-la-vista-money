"""QR-code extraction and parsing for FNS receipt lookup."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Final
from urllib.parse import parse_qs

from PIL import Image, UnidentifiedImageError

REQUIRED_QR_FIELDS: Final[frozenset[str]] = frozenset(
    {'t', 's', 'fn', 'i', 'fp', 'n'},
)


class QRCodeError(ValueError):
    """Base exception for QR extraction failures."""


class QRCodeNotFoundError(QRCodeError):
    """Raised when an uploaded receipt image has no readable QR code."""


class QRCodeDecodeError(QRCodeError):
    """Raised when a QR code is unreadable or missing required FNS fields."""


@dataclass(frozen=True)
class FNSQRCode:
    """Parsed FNS QR payload."""

    raw: str
    t: str
    s: str
    fn: str
    i: str
    fp: str
    n: str

    @property
    def fiscal_key(self) -> str:
        """Return the current fiscal identifier without logging raw QR data."""
        return f'{self.fn}:{self.i}:{self.fp}:{self.n}'


def parse_fns_qr(raw_qr: str) -> FNSQRCode:
    """Parse and validate an FNS QR string."""
    raw = raw_qr.strip()
    if not raw:
        raise QRCodeDecodeError('QR string is empty')

    values = {
        key: parsed_values[0].strip()
        for key, parsed_values in parse_qs(raw, keep_blank_values=True).items()
        if parsed_values
    }
    missing = sorted(
        field for field in REQUIRED_QR_FIELDS if not values.get(field)
    )
    if missing:
        message = f'QR string is missing required fields: {", ".join(missing)}'
        raise QRCodeDecodeError(message)

    return FNSQRCode(
        raw=raw,
        t=values['t'],
        s=values['s'],
        fn=values['fn'],
        i=values['i'],
        fp=values['fp'],
        n=values['n'],
    )


class QRCodeExtractor:
    """Extract FNS QR data from receipt images using pyzbar."""

    def extract(self, image_file: Any) -> FNSQRCode:
        """Read the first valid QR code from an uploaded/persisted image."""
        try:
            pyzbar = import_module('pyzbar.pyzbar')
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise QRCodeDecodeError(
                'pyzbar or system zbar library is not installed',
            ) from exc

        try:
            if hasattr(image_file, 'seek'):
                image_file.seek(0)
            with Image.open(image_file) as image:
                decoded_codes = pyzbar.decode(
                    image,
                    symbols=[pyzbar.ZBarSymbol.QRCODE],
                )
        except (OSError, UnidentifiedImageError) as exc:
            raise QRCodeDecodeError('Receipt image cannot be opened') from exc

        if not decoded_codes:
            raise QRCodeNotFoundError('Receipt image has no QR code')

        for code in decoded_codes:
            data = getattr(code, 'data', b'')
            try:
                raw_qr = data.decode('utf-8')
            except UnicodeDecodeError:
                continue
            try:
                return parse_fns_qr(raw_qr)
            except QRCodeDecodeError:
                continue

        raise QRCodeDecodeError('Receipt QR code is not an FNS QR')


__all__ = [
    'FNSQRCode',
    'QRCodeDecodeError',
    'QRCodeError',
    'QRCodeExtractor',
    'QRCodeNotFoundError',
    'parse_fns_qr',
]
