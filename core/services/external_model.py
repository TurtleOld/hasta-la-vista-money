"""Transport for chat-completion APIs of external models."""

from typing import Any, Final, cast

import httpx

DEFAULT_EXTERNAL_MODEL_TIMEOUT_SECONDS: Final[float] = 10.0


class ExternalModelTransport:
    """Send generic chat-completion requests to an external model."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = DEFAULT_EXTERNAL_MODEL_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip('/')
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

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

        payload = {
            'model': self._model,
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': temperature,
        }
        if response_format is not None:
            payload['response_format'] = response_format
        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.post(
                f'{self._base_url}/chat/completions',
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            raise ValueError('External model returned a non-object response')
        return cast('dict[str, Any]', data)
