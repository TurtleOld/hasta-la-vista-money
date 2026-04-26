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
    )
