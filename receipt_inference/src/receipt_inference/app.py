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
        'qwen_model_path': settings.qwen_model_path,
    }


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    """Load static configuration and perform lightweight startup checks."""
    settings = load_settings()
    service = ReceiptInferenceService(settings)
    app.state.settings = settings
    app.state.service = service
    logger.info(
        'receipt_inference_startup',
        settings=_serialize_settings(settings),
        model_path_exists=service.model_path_exists,
    )
    yield


async def health(_: Request) -> Response:
    """Return health information for the receipt inference service."""
    return OrjsonResponse({'status': 'ok'})


async def readiness(request: Request) -> Response:
    """Return readiness details for orchestration and debugging."""
    settings: ReceiptInferenceSettings = request.app.state.settings
    service: ReceiptInferenceService = request.app.state.service
    return OrjsonResponse(
        {
            'status': 'ready',
            'service': 'receipt-inference',
            'model_path_exists': service.model_path_exists,
            'settings': _serialize_settings(settings),
        },
    )


async def parse_receipt(request: Request) -> Response:
    """Accept a receipt image upload and return structured parse result."""
    started_at = perf_counter()
    service: ReceiptInferenceService = request.app.state.service
    uploaded_file: UploadFile | None = None

    try:
        form = await request.form()
        form_file = form.get('file')
        if isinstance(form_file, UploadFile):
            uploaded_file = form_file

        payload = await service.parse_upload(uploaded_file)
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
            'data': payload,
            'meta': {
                'ocr_ms': 0,
                'llm_ms': 0,
                'total_ms': elapsed_ms,
            },
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
