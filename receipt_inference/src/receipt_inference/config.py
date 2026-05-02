"""Configuration for the receipt inference service."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_RECEIPT_INFERENCE_HOST = '127.0.0.1'


@dataclass(frozen=True)
class ReceiptInferenceSettings:
    """Runtime settings for the receipt inference service."""

    host: str
    port: int
    log_level: str
    max_concurrency: int
    llama_threads: int
    ocr_threads: int
    llama_server_url: str
    llama_timeout: float
    llama_max_tokens: int
    llama_model_alias: str
    max_image_dimension: int
    min_ocr_image_width: int
    jpeg_quality: int
    ocr_language: str
    ocr_min_confidence: float
    ocr_detection_model_name: str
    ocr_recognition_model_name: str
    ocr_use_angle_cls: bool
    ocr_readiness_required: bool
    llama_readiness_required: bool


def load_settings() -> ReceiptInferenceSettings:
    """Load settings from environment variables."""
    return ReceiptInferenceSettings(
        host=os.getenv(
            'RECEIPT_INFERENCE_HOST',
            DEFAULT_RECEIPT_INFERENCE_HOST,
        ),
        port=int(os.getenv('RECEIPT_INFERENCE_PORT', '8010')),
        log_level=os.getenv('RECEIPT_INFERENCE_LOG_LEVEL', 'info'),
        max_concurrency=int(
            os.getenv('RECEIPT_INFERENCE_MAX_CONCURRENCY', '1'),
        ),
        llama_threads=int(os.getenv('LLAMA_THREADS', '4')),
        ocr_threads=int(os.getenv('OCR_THREADS', '2')),
        llama_server_url=os.getenv(
            'LLAMA_SERVER_URL',
            'http://127.0.0.1:8080/v1',
        ).rstrip('/'),
        llama_timeout=float(os.getenv('LLAMA_TIMEOUT', '360')),
        llama_max_tokens=int(os.getenv('LLAMA_MAX_TOKENS', '384')),
        llama_model_alias=os.getenv(
            'LLAMA_MODEL_ALIAS',
            'Qwen2.5-3B-Instruct-Q5_K_M',
        ),
        max_image_dimension=int(os.getenv('MAX_IMAGE_DIMENSION', '2400')),
        min_ocr_image_width=int(os.getenv('MIN_OCR_IMAGE_WIDTH', '1000')),
        jpeg_quality=int(os.getenv('JPEG_QUALITY', '95')),
        ocr_language=os.getenv('OCR_LANGUAGE', 'ru'),
        ocr_min_confidence=float(os.getenv('OCR_MIN_CONFIDENCE', '0.5')),
        ocr_detection_model_name=os.getenv(
            'OCR_DETECTION_MODEL_NAME',
            'PP-OCRv5_mobile_det',
        ),
        ocr_recognition_model_name=os.getenv(
            'OCR_RECOGNITION_MODEL_NAME',
            'PP-OCRv5_server_rec',
        ),
        ocr_use_angle_cls=(
            os.getenv('OCR_USE_ANGLE_CLS', 'false').strip().lower() == 'true'
        ),
        ocr_readiness_required=(
            os.getenv('OCR_READINESS_REQUIRED', 'true').strip().lower()
            == 'true'
        ),
        llama_readiness_required=(
            os.getenv('LLAMA_READINESS_REQUIRED', 'true').strip().lower()
            == 'true'
        ),
    )
