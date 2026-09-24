"""QR-code extraction and parsing for FNS receipt lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import parse_qs

import zxingcpp
from PIL import Image, UnidentifiedImageError

REQUIRED_QR_FIELDS: Final[frozenset[str]] = frozenset(
    {'t', 's', 'fn', 'i', 'fp', 'n'},
)

_READER_OPTIONS: Final[dict[str, Any]] = {
    'formats': zxingcpp.QRCode,
    'try_rotate': True,
    'try_downscale': True,
    'try_invert': True,
    'binarizer': zxingcpp.Binarizer.LocalAverage,
    'text_mode': zxingcpp.TextMode.Plain,
}


class QRCodeError(ValueError):
    """Base exception for QR extraction failures.

    Carries the source image dimensions (when known) so callers can log
    them without reopening the file, e.g. to tell "photo too small" apart
    from "QR physically unreadable" when diagnosing user reports.
    """

    def __init__(
        self,
        message: str,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        super().__init__(message)
        self.width = width
        self.height = height


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
    """Extract FNS QR data from receipt images using zxing-cpp.

    Mirrors the reader options used by the browser camera-scan worker
    (``static/js/pages/receipt-qr-worker.js``), so a photo uploaded via the
    "Файл" tab gets the same rotation/inversion/downscale robustness as a
    live camera scan (see ADR-0011).
    """

    def extract(self, image_file: Any) -> FNSQRCode:
        """Read the first valid QR code from an uploaded/persisted image."""
        width: int | None = None
        height: int | None = None
        try:
            if hasattr(image_file, 'seek'):
                image_file.seek(0)
            with Image.open(image_file) as image:
                width, height = image.size
                decoded_codes = zxingcpp.read_barcodes(
                    image,
                    **_READER_OPTIONS,
                )
        except (OSError, UnidentifiedImageError) as exc:
            raise QRCodeDecodeError(
                'Receipt image cannot be opened',
                width=width,
                height=height,
            ) from exc

        if not decoded_codes:
            raise QRCodeNotFoundError(
                'Receipt image has no QR code',
                width=width,
                height=height,
            )

        for code in decoded_codes:
            raw_qr = code.text
            if not raw_qr:
                continue
            try:
                return parse_fns_qr(raw_qr)
            except QRCodeDecodeError:
                continue

        raise QRCodeDecodeError(
            'Receipt QR code is not an FNS QR',
            width=width,
            height=height,
        )


__all__ = [
    'FNSQRCode',
    'QRCodeDecodeError',
    'QRCodeError',
    'QRCodeExtractor',
    'QRCodeNotFoundError',
    'parse_fns_qr',
]
