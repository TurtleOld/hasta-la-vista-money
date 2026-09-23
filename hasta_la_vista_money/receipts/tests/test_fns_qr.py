"""Characterizing tests for QRCodeExtractor (ADR-0011).

Fixtures are generated with zxing-cpp's own encoder, so the same package
both writes and reads the QR codes under test: no committed binary images,
no extra dev dependency.
"""

from __future__ import annotations

import io

import numpy as np
import zxingcpp
from django.test import SimpleTestCase
from PIL import Image

from hasta_la_vista_money.receipts.services.fns_qr import (
    QRCodeDecodeError,
    QRCodeExtractor,
    QRCodeNotFoundError,
)

_FNS_QR_TEXT = (
    't=20260101T1200&s=1234.56&fn=9999999999999999&i=12345&fp=1234567890&n=1'
)


def _qr_jpeg_bytes(text: str, *, rotate_degrees: int = 0) -> io.BytesIO:
    """Encode ``text`` as a QR code and return it as JPEG bytes.

    Mirrors a phone photo: an RGB JPEG, optionally pixel-rotated the way a
    camera photo taken in portrait orientation would be.
    """
    barcode = zxingcpp.create_barcode(text, zxingcpp.QRCode)
    bitmap = zxingcpp.write_barcode_to_image(barcode, scale=6)
    image = Image.fromarray(np.array(bitmap), mode='L').convert('RGB')
    if rotate_degrees:
        image = image.rotate(rotate_degrees, expand=True)

    buffer = io.BytesIO()
    image.save(buffer, format='JPEG')
    buffer.seek(0)
    buffer.name = 'receipt.jpg'
    return buffer


def _blank_jpeg_bytes(width: int = 200, height: int = 120) -> io.BytesIO:
    image = Image.new('RGB', (width, height), color='white')
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG')
    buffer.seek(0)
    buffer.name = 'blank.jpg'
    return buffer


class QRCodeExtractorTests(SimpleTestCase):
    """extract() is the only surface these tests cross."""

    def setUp(self) -> None:
        self.extractor = QRCodeExtractor()

    def test_extracts_fns_qr_from_upright_photo(self) -> None:
        image_file = _qr_jpeg_bytes(_FNS_QR_TEXT)

        result = self.extractor.extract(image_file)

        self.assertEqual(result.fn, '9999999999999999')
        self.assertEqual(result.i, '12345')
        self.assertEqual(result.fp, '1234567890')
        self.assertEqual(result.n, '1')

    def test_extracts_fns_qr_rotated_90_degrees(self) -> None:
        image_file = _qr_jpeg_bytes(_FNS_QR_TEXT, rotate_degrees=90)

        result = self.extractor.extract(image_file)

        self.assertEqual(result.raw, _FNS_QR_TEXT)

    def test_extracts_fns_qr_rotated_180_degrees(self) -> None:
        image_file = _qr_jpeg_bytes(_FNS_QR_TEXT, rotate_degrees=180)

        result = self.extractor.extract(image_file)

        self.assertEqual(result.raw, _FNS_QR_TEXT)

    def test_extracts_fns_qr_rotated_270_degrees(self) -> None:
        image_file = _qr_jpeg_bytes(_FNS_QR_TEXT, rotate_degrees=270)

        result = self.extractor.extract(image_file)

        self.assertEqual(result.raw, _FNS_QR_TEXT)

    def test_raises_not_found_with_dimensions_when_no_qr_present(
        self,
    ) -> None:
        image_file = _blank_jpeg_bytes(width=200, height=120)

        with self.assertRaises(QRCodeNotFoundError) as ctx:
            self.extractor.extract(image_file)

        self.assertEqual(ctx.exception.width, 200)
        self.assertEqual(ctx.exception.height, 120)

    def test_raises_decode_error_for_non_fns_qr(self) -> None:
        image_file = _qr_jpeg_bytes('https://example.com/not-a-receipt')

        with self.assertRaises(QRCodeDecodeError):
            self.extractor.extract(image_file)

    def test_raises_decode_error_for_unopenable_file(self) -> None:
        image_file = io.BytesIO(b'not an image')

        with self.assertRaises(QRCodeDecodeError) as ctx:
            self.extractor.extract(image_file)

        self.assertIsNone(ctx.exception.width)
        self.assertIsNone(ctx.exception.height)
