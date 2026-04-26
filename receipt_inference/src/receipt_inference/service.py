"""Application service for receipt inference requests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from receipt_inference.errors import ReceiptInferenceError

if TYPE_CHECKING:
    from starlette.datastructures import UploadFile

    from receipt_inference.config import ReceiptInferenceSettings

logger = structlog.get_logger(__name__)

ALLOWED_CONTENT_TYPES = {
    'image/jpeg',
    'image/png',
    'image/webp',
}
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ReceiptFilePayload:
    """Uploaded file data normalized for inference processing."""

    file_name: str
    content_type: str
    file_bytes: bytes

    @property
    def size_bytes(self) -> int:
        """Return the uploaded file size in bytes."""
        return len(self.file_bytes)


class ReceiptInferenceService:
    """Validate receipt uploads and run the inference pipeline."""

    def __init__(self, settings: ReceiptInferenceSettings) -> None:
        self._model_path = Path(settings.qwen_model_path)

    @property
    def model_path_exists(self) -> bool:
        """Whether the configured local Qwen model exists."""
        return self._model_path.exists()

    async def parse_upload(
        self,
        uploaded_file: UploadFile | None,
    ) -> dict[str, Any]:
        """Validate the upload and return normalized API response."""
        payload = await self._read_upload(uploaded_file)
        self._validate_payload(payload)

        if not self.model_path_exists:
            raise ReceiptInferenceError(
                error_code='model_unavailable',
                message='Configured Qwen model file was not found.',
                status_code=503,
            )

        logger.info(
            'receipt_inference_pipeline_not_ready',
            file_name=payload.file_name,
            content_type=payload.content_type,
            file_size=payload.size_bytes,
            qwen_model_path=str(self._model_path),
        )
        raise ReceiptInferenceError(
            error_code='pipeline_not_ready',
            message='Receipt OCR/LLM pipeline is not implemented yet.',
            status_code=501,
        )

    async def _read_upload(
        self,
        uploaded_file: UploadFile | None,
    ) -> ReceiptFilePayload:
        """Read multipart upload into an immutable payload."""
        if uploaded_file is None:
            raise ReceiptInferenceError(
                error_code='missing_file',
                message='Multipart field "file" is required.',
                status_code=400,
            )

        file_name = uploaded_file.filename or 'receipt'
        content_type = uploaded_file.content_type or 'application/octet-stream'
        file_bytes = await uploaded_file.read()
        await uploaded_file.close()

        logger.info(
            'receipt_inference_upload_received',
            file_name=file_name,
            content_type=content_type,
            file_size=len(file_bytes),
        )
        return ReceiptFilePayload(
            file_name=file_name,
            content_type=content_type,
            file_bytes=file_bytes,
        )

    def _validate_payload(self, payload: ReceiptFilePayload) -> None:
        """Validate uploaded file shape before OCR/LLM processing."""
        if not payload.file_bytes:
            raise ReceiptInferenceError(
                error_code='empty_file',
                message='Uploaded receipt image is empty.',
                status_code=400,
            )

        if payload.size_bytes > MAX_UPLOAD_SIZE_BYTES:
            raise ReceiptInferenceError(
                error_code='file_too_large',
                message='Uploaded receipt image exceeds the 10 MB limit.',
                status_code=413,
            )

        if payload.content_type not in ALLOWED_CONTENT_TYPES:
            raise ReceiptInferenceError(
                error_code='invalid_content_type',
                message=(
                    'Only JPEG, PNG, and WEBP receipt images are supported.'
                ),
                status_code=415,
            )
