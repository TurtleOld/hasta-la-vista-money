"""ASGI app for the internal receipt inference service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
import structlog
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from receipt_inference.config import (
    ReceiptInferenceSettings,
    load_settings,
)

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
    model_path = Path(settings.qwen_model_path)
    app.state.settings = settings
    app.state.model_path_exists = model_path.exists()
    logger.info(
        'receipt_inference_startup',
        settings=_serialize_settings(settings),
        model_path_exists=app.state.model_path_exists,
    )
    yield


async def health(_: Request) -> Response:
    """Return health information for the receipt inference service."""
    return OrjsonResponse({'status': 'ok'})


async def readiness(request: Request) -> Response:
    """Return readiness details for orchestration and debugging."""
    settings: ReceiptInferenceSettings = request.app.state.settings
    return OrjsonResponse(
        {
            'status': 'ready',
            'service': 'receipt-inference',
            'model_path_exists': request.app.state.model_path_exists,
            'settings': _serialize_settings(settings),
        },
    )


async def parse_receipt(_: Request) -> Response:
    """Placeholder endpoint for the upcoming OCR -> LLM pipeline."""
    return OrjsonResponse(
        {
            'success': False,
            'error_code': 'not_implemented',
            'message': 'Receipt parsing pipeline is not implemented yet.',
        },
        status_code=501,
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
