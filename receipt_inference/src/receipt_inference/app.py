"""ASGI app for the internal receipt inference service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from typing import TYPE_CHECKING, Any

import orjson
import structlog
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from receipt_inference.config import (
    ReceiptInferenceSettings,
    load_settings,
)
from receipt_inference.errors import ReceiptInferenceError
from receipt_inference.service import ReceiptInferenceService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.requests import Request

logger = structlog.get_logger(__name__)

HTTP_OK = 200


class OrjsonResponse(JSONResponse):
    """JSON response rendered with orjson."""

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)


def _serialize_settings(settings: ReceiptInferenceSettings) -> dict[str, Any]:
    """Serialize safe settings for diagnostics."""
    return {
        'host': settings.host,
        'port': settings.port,
        'log_level': settings.log_level,
        'max_concurrency': settings.max_concurrency,
        'llama_threads': settings.llama_threads,
        'ocr_threads': settings.ocr_threads,
        'llama_server_url': settings.llama_server_url,
        'llama_model_alias': settings.llama_model_alias,
    }


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    """Load configuration and warm up runtime dependencies."""
    settings = load_settings()
    service = ReceiptInferenceService(settings)
    warmup_started_at = perf_counter()

    try:
        service.warmup()
    except ReceiptInferenceError:
        if settings.ocr_readiness_required:
            raise
        logger.warning(
            'receipt_inference_warmup_skipped',
            reason='ocr_readiness_not_required',
            exc_info=True,
        )

    app.state.settings = settings
    app.state.service = service
    logger.info(
        'receipt_inference_startup',
        settings=_serialize_settings(settings),
        readiness=service.readiness_status(),
        warmup_ms=round((perf_counter() - warmup_started_at) * 1000, 2),
    )
    yield


async def health(_: Request) -> Response:
    """Return health information for the receipt inference service."""
    return OrjsonResponse({'status': 'ok'})


async def readiness(request: Request) -> Response:
    """Return readiness details for orchestration and debugging."""
    settings: ReceiptInferenceSettings = request.app.state.settings
    service: ReceiptInferenceService = request.app.state.service
    readiness = service.readiness_status()
    status_code = HTTP_OK if all(readiness.values()) else 503
    return OrjsonResponse(
        {
            'status': 'ready' if status_code == HTTP_OK else 'degraded',
            'service': 'receipt-inference',
            **readiness,
            'settings': _serialize_settings(settings),
        },
        status_code=status_code,
    )


async def parse_receipt(request: Request) -> Response:
    """Accept a receipt image upload and return structured parse result."""
    started_at = perf_counter()
    service: ReceiptInferenceService = request.app.state.service
    uploaded_file: UploadFile | None = None

    try:
        form = await request.form()
        form_file = form.get('file')
        ocr_text_override = form.get('ocr_text')
        if isinstance(form_file, UploadFile):
            uploaded_file = form_file

        payload = await service.parse_upload(
            uploaded_file,
            ocr_text_override=(
                str(ocr_text_override)
                if isinstance(ocr_text_override, str)
                else None
            ),
        )
    except ReceiptInferenceError as exc:
        logger.info(
            'receipt_inference_request_failed',
            error_code=exc.error_code,
            status_code=exc.status_code,
            elapsed_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        return OrjsonResponse(
            {
                'success': False,
                'error_code': exc.error_code,
                'message': exc.message,
            },
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception('receipt_inference_unexpected_error')
        return OrjsonResponse(
            {
                'success': False,
                'error_code': 'internal_error',
                'message': 'Unexpected receipt inference service error.',
            },
            status_code=500,
        )

    elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
    logger.info('receipt_inference_request_succeeded', elapsed_ms=elapsed_ms)
    return OrjsonResponse(
        {
            'success': True,
            'data': payload['data'],
            'meta': payload['meta'] | {'total_ms': elapsed_ms},
        },
    )


app = Starlette(
    debug=False,
    lifespan=lifespan,
    routes=[
        Route('/health', health, methods=['GET']),
        Route('/ready', readiness, methods=['GET']),
        Route('/v1/receipt/parse', parse_receipt, methods=['POST']),
    ],
)
