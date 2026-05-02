"""Receipt inference pipeline components."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
from time import perf_counter, sleep
from typing import TYPE_CHECKING, Any

import httpx
import numpy as np
import structlog
from PIL import (
    Image,
    ImageEnhance,
    ImageFilter,
    ImageOps,
    UnidentifiedImageError,
)

from receipt_inference.errors import ReceiptInferenceError

if TYPE_CHECKING:
    from receipt_inference.config import ReceiptInferenceSettings

logger = structlog.get_logger(__name__)

MIN_OCR_ENTRY_PARTS = 2
LLM_CONNECT_RETRY_COUNT = 3
LLM_CONNECT_RETRY_DELAY_SECONDS = 2.0
JSON_BLOCK_PATTERN = re.compile(
    r'```(?:json)?\s*(\{.*?\})\s*```',
    re.DOTALL,
)
HTTP_CONNECT_TIMEOUT = 10.0
HTTP_WRITE_TIMEOUT = 60.0
HTTP_POOL_TIMEOUT = 60.0
WILDBERRIES_SELLER_NAME = 'ООО "РВБ"'
WILDBERRIES_MARKERS = (
    'wildberries',
    'wb.ru',
    'wailberries',
    'вайлдберриз',
    'вайлдберрис',
    'ооо "рвб"',
    'ооо рвб',
)


@dataclass(frozen=True)
class PreparedImage:
    """Preprocessed image ready for OCR."""

    image_bytes: bytes
    media_type: str
    width: int
    height: int


@dataclass(frozen=True)
class OCRResult:
    """OCR output normalized to ordered text lines."""

    text: str
    line_count: int


@dataclass(frozen=True)
class InferenceResult:
    """Normalized final receipt payload and timing metadata."""

    data: dict[str, Any]
    ocr_ms: float
    llm_ms: float


class ImagePreprocessor:
    """Normalize uploaded images before OCR."""

    def __init__(self, settings: ReceiptInferenceSettings) -> None:
        self._max_dimension = settings.max_image_dimension
        self._min_ocr_image_width = settings.min_ocr_image_width
        self._jpeg_quality = settings.jpeg_quality
        self._optimize_jpeg = settings.optimize_jpeg

    def _upscale_for_ocr(self, image: Image.Image) -> Image.Image:
        """Upscale narrow receipts so small text is easier to detect."""
        width, height = image.size
        if width >= self._min_ocr_image_width or width == 0:
            return image

        scale = self._min_ocr_image_width / width
        resized_width = round(width * scale)
        resized_height = round(height * scale)
        return image.resize(
            (resized_width, resized_height),
            Image.Resampling.LANCZOS,
        )

    def _enhance_for_ocr(self, image: Image.Image) -> Image.Image:
        """Boost contrast and edge sharpness for receipt text."""
        grayscale = ImageOps.grayscale(image)
        contrasted = ImageOps.autocontrast(grayscale, cutoff=1)
        contrasted = ImageEnhance.Contrast(contrasted).enhance(1.15)
        sharpened = contrasted.filter(
            ImageFilter.UnsharpMask(radius=1.5, percent=175, threshold=3),
        )
        return sharpened.convert('RGB')

    def prepare(self, image_bytes: bytes) -> PreparedImage:
        """Validate and normalize an uploaded receipt image."""
        try:
            with Image.open(BytesIO(image_bytes)) as source_image:
                normalized_image = ImageOps.exif_transpose(source_image)
                normalized_image = normalized_image.convert('RGB')
                normalized_image.thumbnail(
                    (self._max_dimension, self._max_dimension),
                    Image.Resampling.LANCZOS,
                )
                normalized_image = self._upscale_for_ocr(normalized_image)
                normalized_image = self._enhance_for_ocr(normalized_image)
                width, height = normalized_image.size

                buffer = BytesIO()
                normalized_image.save(
                    buffer,
                    format='JPEG',
                    quality=self._jpeg_quality,
                    optimize=self._optimize_jpeg,
                )
                normalized_bytes = buffer.getvalue()
        except UnidentifiedImageError as exc:
            raise ReceiptInferenceError(
                error_code='invalid_image',
                message='Uploaded file is not a valid receipt image.',
                status_code=400,
            ) from exc

        return PreparedImage(
            image_bytes=normalized_bytes,
            media_type='image/jpeg',
            width=width,
            height=height,
        )


class StubOCRBackend:
    """Temporary OCR backend placeholder until PaddleOCR is wired in."""

    def extract(self, _: PreparedImage) -> OCRResult:
        """Raise a structured error until OCR integration is available."""
        raise ReceiptInferenceError(
            error_code='ocr_not_ready',
            message='PaddleOCR backend is not implemented yet.',
            status_code=501,
        )


class PaddleOCRBackend:
    """CPU OCR backend powered by PaddleOCR."""

    def __init__(self, settings: ReceiptInferenceSettings) -> None:
        self._settings = settings
        self._ocr_instance: Any | None = None

    def is_available(self) -> bool:
        """Return whether PaddleOCR dependencies are importable."""
        try:
            import_module('paddleocr')
        except ImportError:
            return False
        return True

    def warmup(self) -> None:
        """Load the OCR model ahead of the first real receipt request."""
        self._get_ocr_instance()

    def extract(self, prepared_image: PreparedImage) -> OCRResult:
        """Extract ordered text lines from the prepared receipt image."""
        ocr = self._get_ocr_instance()
        logger.info(
            'receipt_inference_ocr_started',
            image_width=prepared_image.width,
            image_height=prepared_image.height,
            media_type=prepared_image.media_type,
            image_size=len(prepared_image.image_bytes),
            detection_model=self._settings.ocr_detection_model_name,
            recognition_model=self._settings.ocr_recognition_model_name,
            use_angle_cls=self._settings.ocr_use_angle_cls,
        )
        image_array = np.array(Image.open(BytesIO(prepared_image.image_bytes)))

        try:
            result = ocr.predict(image_array)
        except Exception as exc:
            logger.warning(
                'receipt_inference_ocr_processing_failed',
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise ReceiptInferenceError(
                error_code='ocr_failed',
                message='PaddleOCR failed to process the receipt image.',
                status_code=502,
            ) from exc

        lines = self._extract_lines(result)
        filtered_lines = [
            text
            for text, confidence in lines
            if text and confidence >= self._settings.ocr_min_confidence
        ]
        text = '\n'.join(filtered_lines).strip()
        logger.info(
            'receipt_inference_ocr_completed',
            line_count=len(filtered_lines),
            text_length=len(text),
            text_preview=text[:2000],
        )
        return OCRResult(text=text, line_count=len(filtered_lines))

    def _get_ocr_instance(self) -> Any:
        """Create PaddleOCR lazily and reuse it across requests."""
        if self._ocr_instance is not None:
            return self._ocr_instance

        try:
            paddleocr_module = import_module('paddleocr')
            paddleocr_cls = paddleocr_module.PaddleOCR
        except ImportError as exc:
            raise ReceiptInferenceError(
                error_code='ocr_unavailable',
                message='PaddleOCR dependencies are not installed.',
                status_code=503,
            ) from exc

        try:
            ocr_kwargs: dict[str, Any] = {
                'use_doc_orientation_classify': False,
                'use_doc_unwarping': False,
                'use_textline_orientation': self._settings.ocr_use_angle_cls,
                'lang': self._settings.ocr_language,
                'device': 'cpu',
                'enable_hpi': False,
                'enable_mkldnn': False,
                'cpu_threads': self._settings.ocr_threads,
            }
            ocr_kwargs.update(self._get_explicit_model_kwargs())
            self._ocr_instance = paddleocr_cls(**ocr_kwargs)
        except Exception as exc:
            raise ReceiptInferenceError(
                error_code='ocr_unavailable',
                message='Failed to initialize PaddleOCR backend.',
                status_code=503,
            ) from exc
        return self._ocr_instance

    def _get_explicit_model_kwargs(self) -> dict[str, str]:
        """Return explicit model overrides only when configured."""
        model_kwargs: dict[str, str] = {}
        if self._settings.ocr_detection_model_name:
            model_kwargs['text_detection_model_name'] = (
                self._settings.ocr_detection_model_name
            )
        if self._settings.ocr_recognition_model_name:
            model_kwargs['text_recognition_model_name'] = (
                self._settings.ocr_recognition_model_name
            )
        return model_kwargs

    def _extract_lines(self, result: Any) -> list[tuple[str, float]]:
        """Normalize PaddleOCR output into ordered text lines."""
        if not isinstance(result, list) or not result:
            return []

        structured_lines = self._extract_structured_lines(result)
        if structured_lines:
            return structured_lines

        # PaddleOCR commonly returns [[line1, line2, ...]] for a single image.
        first_page = result[0] if isinstance(result[0], list) else result
        if not isinstance(first_page, list):
            return []

        lines: list[tuple[str, float]] = []
        for entry in first_page:
            if not isinstance(entry, list) or len(entry) < MIN_OCR_ENTRY_PARTS:
                continue
            text_meta = entry[1]
            if (
                not isinstance(text_meta, list | tuple)
                or len(text_meta) < MIN_OCR_ENTRY_PARTS
            ):
                continue
            text = str(text_meta[0]).strip()
            try:
                confidence = float(text_meta[1])
            except (TypeError, ValueError):
                confidence = 0.0
            lines.append((text, confidence))
        return lines

    def _extract_structured_lines(
        self,
        result: list[Any],
    ) -> list[tuple[str, float]]:
        """Handle PaddleOCR 3.x object/dict-style prediction results."""
        first_result = result[0]
        texts = self._get_result_field(first_result, 'rec_texts')
        scores = self._get_result_field(first_result, 'rec_scores')
        if not isinstance(texts, list):
            return []

        normalized_scores = scores if isinstance(scores, list) else []
        lines: list[tuple[str, float]] = []
        for index, raw_text in enumerate(texts):
            text = str(raw_text).strip()
            raw_score = (
                normalized_scores[index]
                if index < len(normalized_scores)
                else 0.0
            )
            try:
                confidence = float(raw_score)
            except (TypeError, ValueError):
                confidence = 0.0
            lines.append((text, confidence))
        return lines

    def _get_result_field(self, result: Any, field_name: str) -> Any:
        """Read a field from dict-like or object-like PaddleOCR results."""
        if isinstance(result, dict):
            return result.get(field_name)
        return getattr(result, field_name, None)


class PromptBuilder:
    """Builds the fixed prompt for Qwen receipt extraction."""

    def build_messages(self, ocr_text: str) -> list[dict[str, str]]:
        """Construct an OpenAI-compatible chat payload from OCR text."""
        system_prompt = (
            'Ты извлекаешь структурированные данные из OCR-текста '
            'кассового чека. OCR может содержать ошибки, дубли, переносы '
            'строк и лишние символы. Верни только корректный JSON без '
            'пояснений, markdown-блоков и комментариев. '
            'Ответ должен начинаться с "{" и заканчиваться "}". '
            'Не выдумывай отсутствующие значения. '
            'Повторяющиеся товары не объединяй. '
            'name_seller — это юридический продавец из шапки чека, '
            'а не бренд или название товара.'
        )
        user_prompt = (
            'Преобразуй OCR-текст кассового чека в JSON с ключами '
            'name_seller, retail_place_address, retail_place, total_sum, '
            'operation_type, receipt_date, number_receipt, nds10, nds20, '
            'items. Формат даты: ДД.ММ.ГГГГ ЧЧ:ММ. '
            'operation_type: 1 для покупки, 2 для возврата. '
            'Каждый товар в items должен содержать product_name, category, '
            'price, quantity, amount. Если товара несколько с одинаковым '
            'названием, верни их отдельными элементами.\n\n'
            f'OCR_TEXT:\n{ocr_text}'
        )
        return [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]


class LlamaServerBackend:
    """OpenAI-compatible client for local llama-server."""

    def __init__(self, settings: ReceiptInferenceSettings) -> None:
        self._base_url = settings.llama_server_url
        self._timeout = settings.llama_timeout
        self._max_tokens = settings.llama_max_tokens
        self._prompt_builder = PromptBuilder()
        self._model_alias = settings.llama_model_alias
        self._client = httpx.Client(timeout=self._build_timeout())

    def is_reachable(self) -> bool:
        """Check whether llama-server responds on its OpenAI endpoint."""
        try:
            with httpx.Client(timeout=min(self._timeout, 5.0)) as client:
                response = client.get(f'{self._base_url}/models')
            if not response.is_success:
                return False
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return False

        if not isinstance(payload, dict):
            return False
        models = payload.get('data')
        if not isinstance(models, list):
            return False

        for model in models:
            if not isinstance(model, dict):
                continue
            if str(model.get('id', '')).strip() == self._model_alias:
                return True
        return bool(models)

    def close(self) -> None:
        """Close reusable HTTP resources."""
        self._client.close()

    def _build_timeout(self) -> httpx.Timeout:
        """Use a generous read timeout for local llama generation."""
        return httpx.Timeout(
            connect=HTTP_CONNECT_TIMEOUT,
            read=self._timeout,
            write=HTTP_WRITE_TIMEOUT,
            pool=HTTP_POOL_TIMEOUT,
        )

    def extract(self, ocr_result: OCRResult) -> str:
        """Send OCR text to llama-server and return raw model output."""
        messages = self._prompt_builder.build_messages(ocr_result.text)
        payload = {
            'model': self._model_alias,
            'temperature': 0,
            'max_tokens': self._max_tokens,
            'response_format': {'type': 'json_object'},
            'cache_prompt': True,
            'messages': messages,
        }
        logger.info(
            'receipt_inference_llm_request_started',
            model_alias=self._model_alias,
            timeout=self._timeout,
            max_tokens=self._max_tokens,
            ocr_line_count=ocr_result.line_count,
            ocr_text_length=len(ocr_result.text),
        )

        try:
            response = self._post_chat_completion(payload)
            response.raise_for_status()
            data = response.json()
            content = data['choices'][0]['message']['content']
            if not content:
                raise ReceiptInferenceError(
                    error_code='llm_empty_response',
                    message='Llama server returned an empty receipt response.',
                    status_code=502,
                )
            logger.info(
                'receipt_inference_llm_request_completed',
                model_alias=self._model_alias,
                response_length=len(str(content)),
            )
            return str(content)
        except ReceiptInferenceError:
            raise
        except httpx.TimeoutException as exc:
            raise ReceiptInferenceError(
                error_code='llm_timeout',
                message='Llama server timed out while processing OCR text.',
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            response = getattr(exc, 'response', None)
            logger.warning(
                'receipt_inference_llm_request_failed',
                error_type=type(exc).__name__,
                error=str(exc),
                status_code=(
                    response.status_code if response is not None else None
                ),
                response_text=(
                    response.text[:1000] if response is not None else None
                ),
            )
            raise ReceiptInferenceError(
                error_code='llm_unavailable',
                message='Llama server is unavailable for receipt parsing.',
                status_code=503,
            ) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ReceiptInferenceError(
                error_code='llm_invalid_response',
                message='Llama server returned an invalid receipt payload.',
                status_code=502,
            ) from exc

    def _post_chat_completion(self, payload: dict[str, Any]) -> httpx.Response:
        """Post a chat completion request with short connect retries."""
        last_error: httpx.ConnectError | None = None
        for attempt in range(LLM_CONNECT_RETRY_COUNT):
            try:
                return self._client.post(
                    f'{self._base_url}/chat/completions',
                    json=payload,
                )
            except httpx.ConnectError as exc:
                last_error = exc
                if attempt + 1 == LLM_CONNECT_RETRY_COUNT:
                    break
                sleep(LLM_CONNECT_RETRY_DELAY_SECONDS)

        if last_error is not None:
            raise last_error
        raise RuntimeError('Failed to call llama-server chat completions.')


class StructuredReceiptNormalizer:
    """Convert raw LLM output into project receipt JSON schema."""

    def normalize(
        self,
        raw_output: str,
        *,
        ocr_text: str = '',
    ) -> dict[str, Any]:
        """Parse and sanitize model output into receipt JSON."""
        payload = self._parse_json(raw_output)
        items = payload.get('items')
        if not isinstance(items, list) or not items:
            raise ReceiptInferenceError(
                error_code='invalid_receipt_payload',
                message='Receipt payload must include at least one item.',
                status_code=422,
            )

        normalized_items = [
            self._normalize_item(item)
            for item in items
            if isinstance(item, dict)
        ]
        if not normalized_items:
            raise ReceiptInferenceError(
                error_code='invalid_receipt_payload',
                message='Receipt payload does not contain valid items.',
                status_code=422,
            )

        normalized = {
            'name_seller': self._normalize_text(
                payload.get('name_seller'),
                default='Неизвестный продавец',
            ),
            'retail_place_address': self._normalize_optional_text(
                payload.get('retail_place_address'),
            ),
            'retail_place': self._normalize_optional_text(
                payload.get('retail_place'),
            ),
            'total_sum': self._normalize_decimal_string(
                payload.get('total_sum'),
            ),
            'operation_type': self._normalize_operation_type(
                payload.get('operation_type'),
            ),
            'receipt_date': self._normalize_date(payload.get('receipt_date')),
            'number_receipt': self._normalize_optional_int(
                payload.get('number_receipt'),
            ),
            'nds10': self._normalize_decimal_string(payload.get('nds10', '0')),
            'nds20': self._normalize_decimal_string(payload.get('nds20', '0')),
            'items': normalized_items,
        }
        self._apply_marketplace_corrections(normalized, ocr_text)
        return normalized

    def _parse_json(self, raw_output: str) -> dict[str, Any]:
        """Extract JSON object from a raw LLM response."""
        raw_output = raw_output.strip()
        json_text = self._extract_json_text(raw_output)

        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            logger.warning(
                'receipt_inference_invalid_json_response',
                response_preview=raw_output[:2000],
                extracted_preview=json_text[:2000],
            )
            raise ReceiptInferenceError(
                error_code='invalid_json',
                message='Receipt LLM response is not valid JSON.',
                status_code=502,
            ) from exc

        if not isinstance(payload, dict):
            raise ReceiptInferenceError(
                error_code='invalid_receipt_payload',
                message='Receipt payload must be a JSON object.',
                status_code=422,
            )
        return payload

    def _extract_json_text(self, raw_output: str) -> str:
        """Extract the most likely JSON object from a noisy LLM response."""
        match = JSON_BLOCK_PATTERN.search(raw_output)
        if match:
            return match.group(1).strip()

        start_index = raw_output.find('{')
        if start_index == -1:
            return raw_output

        extracted = self._extract_balanced_json_object(raw_output, start_index)
        return extracted.strip()

    def _extract_balanced_json_object(
        self,
        raw_output: str,
        start_index: int,
    ) -> str:
        """Extract a balanced JSON object starting at the given index."""
        depth = 0
        in_string = False
        escape_next = False

        for index in range(start_index, len(raw_output)):
            char = raw_output[index]
            if escape_next:
                escape_next = False
                continue

            if in_string and char == '\\':
                escape_next = True
                continue

            if char == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == '{':
                depth += 1
                continue

            if char == '}':
                depth -= 1
                if depth == 0:
                    return raw_output[start_index : index + 1]

        return raw_output[start_index:]

    def _apply_marketplace_corrections(
        self,
        receipt_data: dict[str, Any],
        ocr_text: str,
    ) -> None:
        """Correct common marketplace fields deterministically."""
        haystack = self._build_marketplace_haystack(receipt_data, ocr_text)
        if self._contains_any_marker(haystack, WILDBERRIES_MARKERS):
            receipt_data['name_seller'] = WILDBERRIES_SELLER_NAME

    def _build_marketplace_haystack(
        self,
        receipt_data: dict[str, Any],
        ocr_text: str,
    ) -> str:
        """Build normalized text used for marketplace detection."""
        fields = [
            ocr_text,
            str(receipt_data.get('name_seller') or ''),
            str(receipt_data.get('retail_place') or ''),
            str(receipt_data.get('retail_place_address') or ''),
        ]
        return ' '.join(fields).casefold()

    def _contains_any_marker(
        self,
        haystack: str,
        markers: tuple[str, ...],
    ) -> bool:
        """Return whether any normalized marker exists in the text."""
        return any(marker.casefold() in haystack for marker in markers)

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Normalize a single receipt item."""
        return {
            'product_name': self._normalize_text(
                item.get('product_name'),
                default='Неизвестный товар',
            ),
            'category': self._normalize_text(
                item.get('category'),
                default='Прочее',
            ),
            'price': self._normalize_decimal_string(item.get('price')),
            'quantity': self._normalize_decimal_string(item.get('quantity')),
            'amount': self._normalize_decimal_string(item.get('amount')),
        }

    def _normalize_text(self, value: Any, *, default: str) -> str:
        """Normalize required string values."""
        text = self._normalize_optional_text(value)
        return text or default

    def _normalize_optional_text(self, value: Any) -> str | None:
        """Normalize optional string values."""
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _normalize_decimal_string(self, value: Any) -> str:
        """Normalize decimal-like values to two-digit string format."""
        text = self._normalize_optional_text(value)
        if text is None:
            return '0.00'

        text = text.replace(',', '.').replace(' ', '')
        text = re.sub(r'[^0-9.\-]', '', text)
        if not text:
            return '0.00'

        try:
            return f'{float(text):.2f}'
        except ValueError as exc:
            raise ReceiptInferenceError(
                error_code='invalid_receipt_payload',
                message='Receipt payload contains invalid numeric values.',
                status_code=422,
            ) from exc

    def _normalize_optional_int(self, value: Any) -> int | None:
        """Normalize optional integer values."""
        text = self._normalize_optional_text(value)
        if text is None:
            return None
        digits = re.sub(r'[^0-9]', '', text)
        return int(digits) if digits else None

    def _normalize_operation_type(self, value: Any) -> int:
        """Normalize receipt operation type."""
        normalized = self._normalize_optional_int(value)
        return normalized if normalized in {1, 2} else 1

    def _normalize_date(self, value: Any) -> str:
        """Validate the expected receipt datetime format."""
        text = self._normalize_optional_text(value)
        if text is None:
            raise ReceiptInferenceError(
                error_code='invalid_receipt_payload',
                message='Receipt payload must include receipt_date.',
                status_code=422,
            )
        if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}', text):
            raise ReceiptInferenceError(
                error_code='invalid_receipt_payload',
                message='Receipt date must use DD.MM.YYYY HH:MM format.',
                status_code=422,
            )
        return text


class ReceiptInferencePipeline:
    """Coordinates preprocessing, OCR, LLM extraction, and normalization."""

    def __init__(self, settings: ReceiptInferenceSettings) -> None:
        self._settings = settings
        self._preprocessor = ImagePreprocessor(settings)
        self._ocr_backend = PaddleOCRBackend(settings)
        self._llm_backend = LlamaServerBackend(settings)
        self._normalizer = StructuredReceiptNormalizer()

    def readiness_status(self) -> dict[str, bool]:
        """Report pipeline dependency readiness."""
        return {
            'ocr_backend_available': (
                self._ocr_backend.is_available()
                if self._settings.ocr_readiness_required
                else True
            ),
            'llama_server_reachable': (
                self._llm_backend.is_reachable()
                if self._settings.llama_readiness_required
                else True
            ),
        }

    def warmup(self) -> None:
        """Warm up heavy runtime dependencies during service startup."""
        self._ocr_backend.warmup()

    def close(self) -> None:
        """Release reusable backend resources."""
        self._llm_backend.close()

    def preprocess(self, image_bytes: bytes) -> PreparedImage:
        """Preprocess image bytes before OCR."""
        return self._preprocessor.prepare(image_bytes)

    def infer(
        self,
        prepared_image: PreparedImage,
        *,
        ocr_text_override: str | None = None,
    ) -> InferenceResult:
        """Run the OCR -> LLM -> normalization pipeline."""
        ocr_started_at = perf_counter()
        if ocr_text_override is not None:
            ocr_result = OCRResult(
                text=ocr_text_override.strip(),
                line_count=len(ocr_text_override.splitlines()),
            )
        else:
            ocr_result = self._ocr_backend.extract(prepared_image)
        ocr_ms = round((perf_counter() - ocr_started_at) * 1000, 2)

        if not ocr_result.text.strip():
            raise ReceiptInferenceError(
                error_code='ocr_empty_result',
                message='OCR did not extract any receipt text.',
                status_code=422,
            )

        llm_started_at = perf_counter()
        raw_output = self._llm_backend.extract(ocr_result)
        llm_ms = round((perf_counter() - llm_started_at) * 1000, 2)
        normalized = self._normalizer.normalize(
            raw_output,
            ocr_text=ocr_result.text,
        )

        logger.info(
            'receipt_inference_pipeline_completed',
            image_width=prepared_image.width,
            image_height=prepared_image.height,
            ocr_line_count=ocr_result.line_count,
            ocr_ms=ocr_ms,
            llm_ms=llm_ms,
            item_count=len(normalized['items']),
        )
        return InferenceResult(data=normalized, ocr_ms=ocr_ms, llm_ms=llm_ms)
