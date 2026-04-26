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
    qwen_model_path: str
    llama_server_url: str
    llama_timeout: float
    max_image_dimension: int
    jpeg_quality: int
    ocr_language: str
    ocr_min_confidence: float
    ocr_use_angle_cls: bool


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
        llama_threads=int(os.getenv('LLAMA_THREADS', '2')),
        ocr_threads=int(os.getenv('OCR_THREADS', '1')),
        qwen_model_path=os.getenv(
            'QWEN_MODEL_PATH',
            '/models/qwen/qwen2.5-3b-instruct-q5_k_m.gguf',
        ),
        llama_server_url=os.getenv(
            'LLAMA_SERVER_URL',
            'http://127.0.0.1:8080/v1',
        ).rstrip('/'),
        llama_timeout=float(os.getenv('LLAMA_TIMEOUT', '120')),
        max_image_dimension=int(os.getenv('MAX_IMAGE_DIMENSION', '2200')),
        jpeg_quality=int(os.getenv('JPEG_QUALITY', '92')),
        ocr_language=os.getenv('OCR_LANGUAGE', 'ru'),
        ocr_min_confidence=float(os.getenv('OCR_MIN_CONFIDENCE', '0.5')),
        ocr_use_angle_cls=(
            os.getenv('OCR_USE_ANGLE_CLS', 'true').strip().lower() == 'true'
        ),
    )
