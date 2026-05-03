"""Receipt inference pipeline components."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from importlib import import_module
from io import BytesIO
from tempfile import NamedTemporaryFile
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
KEY_VALUE_PAIR_CELLS = 2
FOUR_COLUMN_ROW_CELLS = 4
MIN_SELLER_LINE_LENGTH = 3
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
LEGAL_ENTITY_PREFIXES = (
    'общество с ограниченной ответственностью',
    'акционерное общество',
    'публичное акционерное общество',
    'непубличное акционерное общество',
    'индивидуальный предприниматель',
    'ооо',
    'ао',
    'пао',
    'нао',
    'ип',
)
GENERIC_RECEIPT_LINES = (
    'кассовый',
    'кассовый чек',
    'чек',
    'приход',
    'расход',
    'возврат',
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


@dataclass(frozen=True)
class PaddleOCRVLResult:
    """Raw PaddleOCR-VL output and extracted text for diagnostics."""

    raw_output: str
    extracted_text: str


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


class PaddleOCRVLBackend:
    """Receipt extraction backend powered by PaddleOCR-VL."""

    def __init__(self, settings: ReceiptInferenceSettings) -> None:
        self._settings = settings
        self._pipeline: Any | None = None

    def is_available(self) -> bool:
        """Return whether PaddleOCR-VL dependencies are importable."""
        try:
            paddleocr_module = import_module('paddleocr')
        except ImportError:
            return False
        return hasattr(paddleocr_module, 'PaddleOCRVL')

    def warmup(self) -> None:
        """Load PaddleOCR-VL before the first real receipt request."""
        self._get_pipeline()

    def extract(self, prepared_image: PreparedImage) -> PaddleOCRVLResult:
        """Run PaddleOCR-VL and return a receipt-shaped JSON payload."""
        pipeline = self._get_pipeline()
        logger.info(
            'receipt_inference_paddleocr_vl_started',
            image_width=prepared_image.width,
            image_height=prepared_image.height,
            media_type=prepared_image.media_type,
            image_size=len(prepared_image.image_bytes),
            model_name=self._settings.paddleocr_vl_model_name,
        )

        try:
            with NamedTemporaryFile(suffix='.jpg') as image_file:
                image_file.write(prepared_image.image_bytes)
                image_file.flush()
                result = pipeline.predict(
                    image_file.name,
                    use_layout_detection=True,
                    use_ocr_for_image_block=True,
                    format_block_content=True,
                    max_new_tokens=1024,
                )
        except Exception as exc:
            logger.warning(
                'receipt_inference_paddleocr_vl_failed',
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise ReceiptInferenceError(
                error_code='paddleocr_vl_failed',
                message='PaddleOCR-VL failed to process the receipt image.',
                status_code=502,
            ) from exc

        raw_json = self._build_structured_payload(result)
        extracted_text = self._extract_text(result).strip()
        raw_output = raw_json or self._build_fallback_payload(extracted_text)
        logger.info(
            'receipt_inference_paddleocr_vl_completed',
            text_length=len(extracted_text),
            text_preview=extracted_text[:2000],
            used_structured_payload=bool(raw_json),
        )
        return PaddleOCRVLResult(
            raw_output=raw_output,
            extracted_text=extracted_text,
        )

    def _get_pipeline(self) -> Any:
        """Create PaddleOCR-VL lazily and reuse it across requests."""
        if self._pipeline is not None:
            return self._pipeline

        try:
            paddleocr_module = import_module('paddleocr')
            paddleocr_vl_cls = paddleocr_module.PaddleOCRVL
        except (ImportError, AttributeError) as exc:
            raise ReceiptInferenceError(
                error_code='paddleocr_vl_unavailable',
                message='PaddleOCR-VL dependencies are not installed.',
                status_code=503,
            ) from exc

        try:
            kwargs: dict[str, Any] = {'device': 'cpu'}
            if self._settings.paddleocr_vl_model_name:
                kwargs['vl_rec_model_name'] = (
                    self._settings.paddleocr_vl_model_name
                )
            self._pipeline = paddleocr_vl_cls(**kwargs)
        except Exception as exc:
            raise ReceiptInferenceError(
                error_code='paddleocr_vl_unavailable',
                message='Failed to initialize PaddleOCR-VL backend.',
                status_code=503,
            ) from exc
        return self._pipeline

    def _build_structured_payload(self, value: Any) -> str | None:
        """Build a receipt payload from JSON, tables, or OCR text."""
        for text in self._iter_text_values(value):
            stripped = text.strip()
            if not stripped:
                continue
            json_match = JSON_BLOCK_PATTERN.search(stripped)
            candidate = json_match.group(1) if json_match else stripped
            if not candidate.startswith('{'):
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and 'items' in payload:
                return json.dumps(payload, ensure_ascii=False)

        result_data = self._extract_result_data(value)
        parsing_blocks = result_data.get('parsing_res_list')
        if isinstance(parsing_blocks, list):
            payload = self._build_payload_from_blocks(parsing_blocks)
            if payload is not None:
                return json.dumps(payload, ensure_ascii=False)
        return None

    def _extract_result_data(self, value: Any) -> dict[str, Any]:
        """Return the JSON payload from the first PaddleOCR-VL result."""
        if isinstance(value, list | tuple):
            if not value:
                return {}
            return self._extract_result_data(value[0])

        json_payload = getattr(value, 'json', None)
        if isinstance(json_payload, dict):
            result_data = json_payload.get('res')
            return (
                result_data if isinstance(result_data, dict) else json_payload
            )

        if isinstance(value, dict):
            result_data = value.get('res')
            return result_data if isinstance(result_data, dict) else value
        return {}

    def _build_payload_from_blocks(
        self,
        blocks: list[Any],
    ) -> dict[str, Any] | None:
        """Convert PaddleOCR-VL layout blocks into receipt JSON."""
        title_text, combined_text, metadata, payload = (
            self._collect_payload_parts(blocks)
        )
        self._apply_common_payload_fields(
            payload,
            title_text=title_text,
            combined_text=combined_text,
            metadata=metadata,
        )
        if not payload['items']:
            payload['items'] = self._extract_items_from_text(combined_text)
        if not payload['items']:
            return None
        return payload

    def _collect_payload_parts(
        self,
        blocks: list[Any],
    ) -> tuple[str, str, dict[str, str], dict[str, Any]]:
        """Collect title, text, metadata, and partial payload from blocks."""
        title_text = ''
        combined_text_parts: list[str] = []
        payload: dict[str, Any] = {
            'name_seller': '',
            'retail_place_address': None,
            'retail_place': None,
            'total_sum': '0.00',
            'operation_type': 1,
            'receipt_date': self._extract_receipt_date(''),
            'number_receipt': None,
            'nds10': '0',
            'nds20': '0',
            'items': [],
        }
        metadata: dict[str, str] = {}

        for block in blocks:
            if not isinstance(block, dict):
                continue
            label = str(block.get('block_label', '')).strip().lower()
            content = self._clean_block_content(block.get('block_content'))
            if content:
                combined_text_parts.append(content)
            if label == 'doc_title' and not title_text:
                title_text = content
            if label == 'table':
                table_data = self._parse_receipt_table(
                    str(block.get('block_content', '')),
                )
                if table_data['items']:
                    payload['items'] = table_data['items']
                metadata.update(table_data['metadata'])
                if table_data['total_sum'] != '0.00':
                    payload['total_sum'] = table_data['total_sum']

        combined_text = '\n'.join(part for part in combined_text_parts if part)
        text_metadata = self._extract_metadata_from_text(combined_text)
        metadata = text_metadata | metadata
        return title_text, combined_text, metadata, payload

    def _apply_common_payload_fields(
        self,
        payload: dict[str, Any],
        *,
        title_text: str,
        combined_text: str,
        metadata: dict[str, str],
    ) -> None:
        """Fill common receipt fields from text and metadata."""
        payload['operation_type'] = self._extract_operation_type(
            f'{title_text}\n{combined_text}',
        )
        payload['name_seller'] = self._extract_legal_entity_name(combined_text)
        if not payload['name_seller']:
            payload['name_seller'] = self._extract_seller_name_from_title(
                title_text,
            )
        if not payload['name_seller']:
            payload['name_seller'] = self._extract_seller_name(combined_text)

        payload['retail_place'] = self._get_metadata_value(
            metadata,
            ('Место расчетов', 'Торговая точка', 'Место продажи'),
        )
        if not payload['retail_place']:
            payload['retail_place'] = self._extract_url_like_value(
                combined_text,
            )
        payload['retail_place_address'] = self._get_metadata_value(
            metadata,
            (
                'Адрес расчетов',
                'Адрес торговой точки',
                'Адрес',
                'Адрес места расчетов',
            ),
        )
        payload['receipt_date'] = self._extract_receipt_date(
            self._get_metadata_value(metadata, ('Дата/Время', 'Дата время'))
            or combined_text,
        )
        payload['number_receipt'] = self._extract_receipt_number(
            metadata,
            combined_text,
        )
        payload['nds10'] = self._extract_tax_amount(
            self._get_tax_source(metadata, combined_text),
            ('10',),
        )
        payload['nds20'] = self._extract_tax_amount(
            self._get_tax_source(metadata, combined_text),
            ('20', '22', '122'),
        )
        if payload['total_sum'] == '0.00':
            payload['total_sum'] = self._extract_total_sum(combined_text)

    def _parse_receipt_table(self, table_html: str) -> dict[str, Any]:
        """Extract line items and metadata from PaddleOCR-VL table HTML."""
        rows = self._extract_html_rows(table_html)
        items: list[dict[str, str]] = []
        metadata: dict[str, str] = {}
        total_sum = '0.00'
        pending_name: str | None = None
        for row in rows:
            non_empty = [cell for cell in row if cell]
            if not non_empty:
                continue
            if self._is_table_header_row(non_empty):
                continue
            if len(non_empty) == 1 and not self._is_metadata_label(
                non_empty[0],
            ):
                pending_name = non_empty[0]
                continue
            if self._looks_like_item_row(row, pending_name):
                item = self._build_item_from_row(row, pending_name)
                if item is not None:
                    items.append(item)
                    pending_name = None
                continue
            if self._is_total_row(non_empty):
                if self._looks_like_amount(non_empty[-1]):
                    total_sum = self._normalize_amount_text(non_empty[-1])
                continue
            metadata.update(self._extract_metadata_from_row(row))
            pending_name = None
        return {
            'items': items,
            'metadata': metadata,
            'total_sum': total_sum,
        }

    def _extract_html_rows(self, table_html: str) -> list[list[str]]:
        """Parse simple HTML table rows produced by PaddleOCR-VL."""
        rows: list[list[str]] = []
        for row_html in re.findall(
            r'<tr[^>]*>(.*?)</tr>',
            table_html,
            re.DOTALL,
        ):
            cells = [
                self._clean_block_content(self._strip_tags(cell_html))
                for cell_html in re.findall(
                    r'<t[dh][^>]*>(.*?)</t[dh]>',
                    row_html,
                    re.DOTALL,
                )
            ]
            rows.append(cells)
        return rows

    def _strip_tags(self, value: str) -> str:
        """Remove HTML tags and decode entities."""
        return unescape(re.sub(r'<[^>]+>', ' ', value))

    def _clean_block_content(self, value: Any) -> str:
        """Normalize OCR/VL block content into plain text."""
        text = str(value or '')
        text = self._strip_tags(text)
        text = re.sub(r'^[#*\s]+', '', text)
        return re.sub(r'\s+', ' ', text).strip()

    def _is_table_header_row(self, cells: list[str]) -> bool:
        """Return whether the row is the items header row."""
        header = ' '.join(cell.lower() for cell in cells)
        return (
            'предмет расчета' in header
            and 'цена' in header
            and 'кол-во' in header
        )

    def _looks_like_item_row(
        self,
        cells: list[str],
        pending_name: str | None,
    ) -> bool:
        """Return whether a table row looks like an item row."""
        return self._build_item_from_row(cells, pending_name) is not None

    def _build_item_from_row(
        self,
        cells: list[str],
        pending_name: str | None,
    ) -> dict[str, str] | None:
        """Build a normalized item payload from a parsed row."""
        amount = self._extract_row_amount(cells)
        price, quantity = self._extract_row_price_quantity(cells)
        name = self._extract_row_item_name(cells, pending_name)
        if not name or amount is None or price is None or quantity is None:
            return None
        return {
            'product_name': re.sub(r'^\d+[.)]?\s*', '', name).strip(),
            'category': 'Другое',
            'price': price,
            'quantity': quantity,
            'amount': amount,
        }

    def _extract_row_item_name(
        self,
        cells: list[str],
        pending_name: str | None,
    ) -> str | None:
        """Extract an item name from a table row."""
        if pending_name:
            return pending_name
        for cell in cells:
            normalized = cell.strip()
            if not normalized or self._is_metadata_label(normalized):
                continue
            if self._looks_like_amount(normalized):
                continue
            if self._looks_like_quantity(normalized):
                continue
            if self._extract_price_quantity_pair(normalized) is not None:
                continue
            return normalized
        return None

    def _extract_row_amount(self, cells: list[str]) -> str | None:
        """Extract the total amount column from a row."""
        for cell in reversed(cells):
            if self._looks_like_amount(cell):
                return self._normalize_amount_text(cell)
        return None

    def _extract_row_price_quantity(
        self,
        cells: list[str],
    ) -> tuple[str | None, str | None]:
        """Extract price and quantity from standard or compact row cells."""
        if (
            len(cells) >= FOUR_COLUMN_ROW_CELLS
            and self._looks_like_amount(cells[1])
            and self._looks_like_quantity(cells[2])
            and self._looks_like_amount(cells[3])
        ):
            return (
                self._normalize_amount_text(cells[1]),
                self._normalize_quantity_text(cells[2]),
            )

        for cell in cells:
            pair = self._extract_price_quantity_pair(cell)
            if pair is not None:
                return pair

        amount_cells = [cell for cell in cells if self._looks_like_amount(cell)]
        quantity_cells = [
            cell for cell in cells if self._looks_like_quantity(cell)
        ]
        if len(amount_cells) >= KEY_VALUE_PAIR_CELLS and quantity_cells:
            return (
                self._normalize_amount_text(amount_cells[0]),
                self._normalize_quantity_text(quantity_cells[0]),
            )
        return (None, None)

    def _extract_price_quantity_pair(
        self,
        value: str,
    ) -> tuple[str, str] | None:
        """Parse compact item notation like `59.99*1`."""
        match = re.fullmatch(
            r'(\d+[\d\s]*[,.]\d{2})\s*[*xх]\s*(\d+(?:[,.]\d+)?)',
            value.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return (
            self._normalize_amount_text(match.group(1)),
            self._normalize_quantity_text(match.group(2)),
        )

    def _is_total_row(self, cells: list[str]) -> bool:
        """Return whether the row contains the overall receipt total."""
        label = cells[0].lower()
        return label.startswith('итог') or 'к оплате' in label

    def _extract_metadata_from_row(self, cells: list[str]) -> dict[str, str]:
        """Convert a non-item table row into key-value metadata."""
        non_empty = [cell for cell in cells if cell]
        if len(non_empty) == KEY_VALUE_PAIR_CELLS:
            return {self._normalize_metadata_key(non_empty[0]): non_empty[1]}
        if len(non_empty) == FOUR_COLUMN_ROW_CELLS:
            return {
                self._normalize_metadata_key(non_empty[0]): non_empty[1],
                self._normalize_metadata_key(non_empty[2]): non_empty[3],
            }
        return {}

    def _normalize_metadata_key(self, value: str) -> str:
        """Normalize metadata keys for later lookup."""
        return value.strip().rstrip(':')

    def _extract_metadata_from_text(self, text: str) -> dict[str, str]:
        """Extract simple key-value receipt metadata from plain OCR text."""
        metadata: dict[str, str] = {}
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        index = 0
        while index < len(lines):
            line = lines[index]
            if ':' in line:
                key, _, value = line.partition(':')
                key = self._normalize_metadata_key(key)
                value = value.strip()
                if not value and index + 1 < len(lines):
                    next_line = lines[index + 1].strip()
                    if next_line and not self._looks_like_metadata_only_key(
                        next_line,
                    ):
                        value = next_line
                        index += 1
                if key and value:
                    metadata[key] = value
            elif self._looks_like_metadata_only_key(line) and index + 1 < len(
                lines,
            ):
                metadata[self._normalize_metadata_key(line)] = lines[
                    index + 1
                ].strip()
                index += 1
            index += 1
        return metadata

    def _looks_like_metadata_only_key(self, value: str) -> bool:
        """Return whether a line looks like a standalone metadata key."""
        normalized = value.casefold().strip(' :.-')
        keys = (
            'дата/время',
            'дата время',
            'чек №',
            'фд №',
            'версия ффд',
            'фн',
            'рн ккт',
            'фп',
            'кассир',
            'место расчетов',
            'адрес расчетов',
            'инн',
            'торговая точка',
            'адрес места расчетов',
        )
        return normalized in keys

    def _is_metadata_label(self, value: str) -> bool:
        """Return whether a row label looks like metadata, not an item."""
        normalized = value.lower().strip()
        return normalized.startswith(
            (
                'итог',
                'подытог',
                'наличные',
                'безналичные',
                'предоплата',
                'скидка',
                'округление',
                'принято',
                'сдача',
                'инн',
                '№',
                'чек №',
                'дата/время',
                'версия ффд',
                'фн',
                'фп',
                'рн ккт',
                'кассир',
                'место расчетов',
                'адрес расчетов',
                'ндс',
                'нас ',
                'сумма нас',
            ),
        )

    def _looks_like_amount(self, value: str) -> bool:
        """Return whether text looks like a money amount."""
        return bool(re.fullmatch(r'\d+[\d\s]*[,.]\d{2}', value.strip()))

    def _looks_like_quantity(self, value: str) -> bool:
        """Return whether text looks like a quantity."""
        return bool(re.fullmatch(r'\d+(?:[,.]\d+)?', value.strip()))

    def _normalize_amount_text(self, value: str) -> str:
        """Normalize a money amount into decimal-string format."""
        return value.replace(' ', '').replace(',', '.')

    def _normalize_quantity_text(self, value: str) -> str:
        """Normalize quantity while preserving integral values."""
        normalized = value.replace(' ', '').replace(',', '.')
        return normalized.removesuffix('.0')

    def _extract_operation_type(self, text: str) -> int:
        """Map receipt text to purchase or refund operation type."""
        lowered = text.lower()
        if 'возврат' in lowered or 'расход' in lowered:
            return 2
        return 1

    def _extract_seller_name_from_title(self, text: str) -> str:
        """Extract seller name from the document title block."""
        if not text:
            return ''
        cleaned = re.sub(
            r'\b(кассовый чек|приход|расход|возврат|чек)\b',
            ' ',
            text,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r'\s+', ' ', cleaned).strip(' -')
        if self._is_generic_receipt_line(cleaned):
            return ''
        return cleaned[:255]

    def _extract_legal_entity_name(self, text: str) -> str:
        """Extract seller legal entity from OCR text when available."""
        flattened = re.sub(r'\s+', ' ', text).strip()
        patterns = (
            r'(?:общество с ограниченной ответственностью|'
            r'акционерное общество|'
            r'публичное акционерное общество|'
            r'непубличное акционерное общество)\s+"[^"]+"',
            r'(?:ООО|АО|ПАО|НАО)\s+"[^"]+"',
            r'ИП\s+[А-ЯA-ZЁ][^\n,]{3,120}',
        )
        for pattern in patterns:
            match = re.search(pattern, flattened, flags=re.IGNORECASE)
            if match:
                return self._normalize_legal_entity_name(match.group(0))

        for line in text.splitlines():
            normalized = self._clean_block_content(line)
            if not normalized:
                continue
            lowered = normalized.casefold()
            if any(
                lowered.startswith(prefix) for prefix in LEGAL_ENTITY_PREFIXES
            ):
                return self._normalize_legal_entity_name(normalized)
        return ''

    def _normalize_legal_entity_name(self, value: str) -> str:
        """Normalize common legal entity names to readable casing."""
        normalized = re.sub(r'\s+', ' ', value).strip(' ,.-')
        replacements = {
            'общество с ограниченной ответственностью': (
                'Общество с ограниченной ответственностью'
            ),
            'акционерное общество': 'Акционерное общество',
            'публичное акционерное общество': 'Публичное акционерное общество',
            'непубличное акционерное общество': (
                'Непубличное акционерное общество'
            ),
            'ооо': 'ООО',
            'ао': 'АО',
            'пао': 'ПАО',
            'нао': 'НАО',
            'ип': 'ИП',
        }
        for source, target in replacements.items():
            normalized = re.sub(
                rf'^{source}\b',
                target,
                normalized,
                flags=re.IGNORECASE,
            )
        return normalized[:255]

    def _is_generic_receipt_line(self, value: str) -> bool:
        """Return whether a line is a generic non-seller receipt heading."""
        lowered = value.casefold().strip(' :.-')
        return lowered in GENERIC_RECEIPT_LINES

    def _get_metadata_value(
        self,
        metadata: dict[str, str],
        keys: tuple[str, ...],
    ) -> str | None:
        """Return the first matching metadata value by key."""
        for key in keys:
            for meta_key, meta_value in metadata.items():
                if meta_key.lower() == key.lower():
                    return meta_value.strip()
        return None

    def _extract_receipt_number(
        self,
        metadata: dict[str, str],
        text: str,
    ) -> int | None:
        """Extract the receipt number from metadata or OCR text."""
        value = self._get_metadata_value(
            metadata,
            ('Чек №', 'Чек N', 'Чек № '),
        )
        if value and value.strip().isdigit():
            return int(value.strip())
        source = value or text
        match = re.search(
            r'чек\s*[№n]?\s*[:.]?\s*(\d+)',
            source,
            re.IGNORECASE,
        )
        return int(match.group(1)) if match else None

    def _extract_url_like_value(self, text: str) -> str | None:
        """Extract a URL or host-like value from OCR text."""
        match = re.search(
            r'(https?://[^\s]+|(?:www\.)?[a-z0-9-]+\.[a-z]{2,}(?:/[^\s]*)?)',
            text,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else None

    def _get_tax_source(self, metadata: dict[str, str], text: str) -> str:
        """Join metadata and OCR text for tax extraction."""
        parts = [text]
        parts.extend(f'{key} {value}' for key, value in metadata.items())
        return '\n'.join(parts)

    def _extract_tax_amount(self, text: str, rates: tuple[str, ...]) -> str:
        """Extract VAT amount for the provided tax rates."""
        flattened = re.sub(r'\s+', ' ', text).strip()
        for rate in rates:
            patterns = (
                rf'ндс[^\n]*{rate}%?[^\d]{{0,40}}(\d+[\d\s]*[,.]\d{{2}})',
                rf'{rate}%?[^\d]{{0,20}}ндс[^\d]{{0,40}}(\d+[\d\s]*[,.]\d{{2}})',
                rf'ставк\w*\s*{rate}%?[^\d]{{0,40}}(\d+[\d\s]*[,.]\d{{2}})',
            )
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    return self._normalize_amount_text(match.group(1))
                match = re.search(pattern, flattened, flags=re.IGNORECASE)
                if match:
                    return self._normalize_amount_text(match.group(1))
        if 'ндс не облагается' in flattened.casefold():
            return '0'
        return '0'

    def _extract_items_from_text(self, text: str) -> list[dict[str, str]]:
        """Fallback item parser for plain OCR text receipts."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        items: list[dict[str, str]] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not re.match(r'^\d+[.)]?', line):
                index += 1
                continue

            name_parts = [re.sub(r'^\d+[.)]?\s*', '', line).strip()]
            price = quantity = amount = None
            look_ahead = index + 1
            while look_ahead < len(lines):
                current = lines[look_ahead]
                if self._looks_like_amount(current) and price is None:
                    price = self._normalize_amount_text(current)
                elif (
                    self._looks_like_quantity(current)
                    and price is not None
                    and quantity is None
                ):
                    quantity = self._normalize_quantity_text(current)
                elif (
                    self._looks_like_amount(current)
                    and quantity is not None
                    and amount is None
                ):
                    amount = self._normalize_amount_text(current)
                    break
                elif not self._is_metadata_label(current):
                    name_parts.append(current)
                look_ahead += 1

            if price and quantity and amount:
                items.append(
                    {
                        'product_name': ' '.join(
                            part for part in name_parts if part
                        ),
                        'category': 'Другое',
                        'price': price,
                        'quantity': quantity,
                        'amount': amount,
                    },
                )
            index = look_ahead + 1
        return items

    def _extract_text(self, value: Any) -> str:
        """Flatten useful textual PaddleOCR-VL output into plain text."""
        lines = [text.strip() for text in self._iter_text_values(value)]
        return '\n'.join(line for line in lines if line)

    def _iter_text_values(self, value: Any) -> list[str]:
        """Collect text-like fields from nested PaddleOCR-VL results."""
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, bytes):
            return [value.decode(errors='ignore')]
        if isinstance(value, dict):
            return self._iter_mapping_text_values(value)
        if isinstance(value, list | tuple):
            return self._iter_sequence_text_values(value)
        return self._iter_object_text_values(value)

    def _iter_mapping_text_values(self, value: dict[Any, Any]) -> list[str]:
        """Collect text-like fields from a mapping."""
        values = []
        for key, item in value.items():
            is_text_key = key in {'text', 'content', 'markdown', 'html', 'json'}
            is_nested = isinstance(item, dict | list | tuple)
            if is_text_key or is_nested:
                values.extend(self._iter_text_values(item))
        return values

    def _iter_sequence_text_values(
        self,
        value: list[Any] | tuple[Any, ...],
    ) -> list[str]:
        """Collect text-like fields from a sequence."""
        values = []
        for item in value:
            values.extend(self._iter_text_values(item))
        return values

    def _iter_object_text_values(self, value: Any) -> list[str]:
        """Collect text-like fields from object attributes."""
        values = []
        for attr_name in ('text', 'content', 'markdown', 'json'):
            attr = getattr(value, attr_name, None)
            if attr is not None:
                values.extend(self._iter_text_values(attr))
        return values

    def _build_fallback_payload(self, text: str) -> str:
        """Build a minimal valid receipt payload when VL returns text only."""
        total_sum = self._extract_total_sum(text)
        payload = {
            'name_seller': self._extract_seller_name(text),
            'retail_place_address': None,
            'retail_place': None,
            'total_sum': total_sum,
            'operation_type': 1,
            'receipt_date': self._extract_receipt_date(text),
            'number_receipt': None,
            'nds10': '0',
            'nds20': '0',
            'items': [
                {
                    'product_name': 'Позиции из чека',
                    'category': 'Другое',
                    'price': total_sum,
                    'quantity': '1',
                    'amount': total_sum,
                },
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    def _extract_seller_name(self, text: str) -> str:
        """Use the first meaningful line as a local fallback seller name."""
        for line in text.splitlines():
            normalized = line.strip(' :-\t')
            if len(
                normalized,
            ) >= MIN_SELLER_LINE_LENGTH and not self._is_generic_receipt_line(
                normalized,
            ):
                return normalized[:255]
        return 'Неизвестный продавец'

    def _extract_receipt_date(self, text: str) -> str:
        """Extract DD.MM.YYYY HH:MM from VL text or use a stable fallback."""
        match = re.search(
            r'(\d{2}\.\d{2}\.\d{4})\D{1,5}(\d{2}:\d{2})',
            text,
        )
        if match:
            return f'{match.group(1)} {match.group(2)}'
        return '01.01.1970 00:00'

    def _extract_total_sum(self, text: str) -> str:
        """Extract a plausible total amount from VL text."""
        amount_pattern = r'(\d+[\s\d]*[,.]\d{2})'
        for marker in ('итог', 'к оплате', 'сумма', 'total'):
            match = re.search(
                rf'{marker}[^\d]{{0,30}}{amount_pattern}',
                text,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1).replace(' ', '').replace(',', '.')

        amounts = [
            float(match.replace(' ', '').replace(',', '.'))
            for match in re.findall(amount_pattern, text)
        ]
        if amounts:
            return f'{max(amounts):.2f}'
        return '0.00'


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
        if text in {'-', '--', '---'}:
            return None
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
        self._ocr_backend: PaddleOCRBackend | None = None
        self._llm_backend: LlamaServerBackend | None = None
        self._paddleocr_vl_backend: PaddleOCRVLBackend | None = None
        if settings.inference_backend == 'paddleocr_vl':
            self._paddleocr_vl_backend = PaddleOCRVLBackend(settings)
        else:
            self._ocr_backend = PaddleOCRBackend(settings)
            self._llm_backend = LlamaServerBackend(settings)
        self._normalizer = StructuredReceiptNormalizer()

    def readiness_status(self) -> dict[str, bool]:
        """Report pipeline dependency readiness."""
        if self._paddleocr_vl_backend is not None:
            return {
                'paddleocr_vl_backend_available': (
                    self._paddleocr_vl_backend.is_available()
                    if self._settings.ocr_readiness_required
                    else True
                ),
            }

        if self._ocr_backend is None or self._llm_backend is None:
            return {'pipeline_configured': False}

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
        if self._paddleocr_vl_backend is not None:
            self._paddleocr_vl_backend.warmup()
            return
        if self._ocr_backend is not None:
            self._ocr_backend.warmup()

    def close(self) -> None:
        """Release reusable backend resources."""
        if self._llm_backend is not None:
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
        if self._paddleocr_vl_backend is not None:
            extraction_started_at = perf_counter()
            if ocr_text_override is not None:
                vl_result = PaddleOCRVLResult(
                    raw_output=ocr_text_override.strip(),
                    extracted_text=ocr_text_override.strip(),
                )
            else:
                vl_result = self._paddleocr_vl_backend.extract(prepared_image)
            extraction_ms = round(
                (perf_counter() - extraction_started_at) * 1000,
                2,
            )
            normalized = self._normalizer.normalize(
                vl_result.raw_output,
                ocr_text=vl_result.extracted_text,
            )
            logger.info(
                'receipt_inference_pipeline_completed',
                image_width=prepared_image.width,
                image_height=prepared_image.height,
                ocr_line_count=len(vl_result.extracted_text.splitlines()),
                ocr_ms=extraction_ms,
                llm_ms=0,
                item_count=len(normalized['items']),
            )
            return InferenceResult(
                data=normalized,
                ocr_ms=extraction_ms,
                llm_ms=0,
            )

        ocr_started_at = perf_counter()
        if ocr_text_override is not None:
            ocr_result = OCRResult(
                text=ocr_text_override.strip(),
                line_count=len(ocr_text_override.splitlines()),
            )
        else:
            if self._ocr_backend is None:
                raise ReceiptInferenceError(
                    error_code='ocr_unavailable',
                    message='OCR backend is not configured.',
                    status_code=503,
                )
            ocr_result = self._ocr_backend.extract(prepared_image)
        ocr_ms = round((perf_counter() - ocr_started_at) * 1000, 2)

        if not ocr_result.text.strip():
            raise ReceiptInferenceError(
                error_code='ocr_empty_result',
                message='OCR did not extract any receipt text.',
                status_code=422,
            )

        if self._llm_backend is None:
            raise ReceiptInferenceError(
                error_code='llm_unavailable',
                message='Llama server backend is not configured.',
                status_code=503,
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
