"""Transport for chat-completion APIs of external models."""

import json
from typing import Any, Final, cast

import httpx

DEFAULT_EXTERNAL_MODEL_TIMEOUT_SECONDS: Final[float] = 10.0
ERROR_BODY_EXCERPT_CHARS: Final = 500


class ExternalModelTransport:
    """Send generic chat-completion requests to an external model."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = DEFAULT_EXTERNAL_MODEL_TIMEOUT_SECONDS,
        json_schema_supported: bool = True,
        reasoning_effort: str = '',
    ) -> None:
        self._base_url = base_url.rstrip('/')
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._json_schema_supported = json_schema_supported
        self._reasoning_effort = reasoning_effort

    def complete(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a chat-completion response from the configured model."""
        headers = {'Content-Type': 'application/json'}
        if self._api_key:
            headers['Authorization'] = f'Bearer {self._api_key}'

        if (
            response_format is not None
            and response_format.get('type') == 'json_schema'
            and not self._json_schema_supported
        ):
            # Providers like DeepSeek accept only json_object, so the schema
            # moves into the prompt; callers still validate the reply.
            schema = response_format['json_schema']['schema']
            messages = [
                *messages,
                {
                    'role': 'system',
                    'content': 'Ответь только JSON-объектом по схеме: '
                    + json.dumps(schema, ensure_ascii=False),
                },
            ]
            response_format = {'type': 'json_object'}

        payload: dict[str, Any] = {
            'model': self._model,
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': temperature,
        }
        if response_format is not None:
            payload['response_format'] = response_format
        if self._reasoning_effort:
            payload['reasoning_effort'] = self._reasoning_effort
        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.post(
                f'{self._base_url}/chat/completions',
                headers=headers,
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                body = response.text[:ERROR_BODY_EXCERPT_CHARS]
                message = f'{error}\n{body}'
                raise httpx.HTTPStatusError(
                    message,
                    request=error.request,
                    response=error.response,
                ) from error
            data = response.json()

        if not isinstance(data, dict):
            raise ValueError('External model returned a non-object response')
        return cast('dict[str, Any]', data)
