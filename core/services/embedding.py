"""Client for the standalone product-name embedding service.

The embedding model runs in its own container with a network interface (it
is never loaded into the task-processing process, to keep memory usage low
there) and is reached over HTTP through an OpenAI-compatible ``/embeddings``
endpoint.
"""

from __future__ import annotations

from typing import Any, Protocol, cast, runtime_checkable

import httpx

DEFAULT_EMBEDDING_TIMEOUT_SECONDS = 10.0


class EmbeddingServiceError(Exception):
    """Raised when the embedding service is unavailable or misbehaves."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Swappable provider of text embeddings."""

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for ``text``.

        Raises:
            EmbeddingServiceError: If the vector could not be obtained.
        """
        ...


class NoopEmbeddingProvider:
    """Used when no embedding service is configured.

    Always raises so the semantic-match stage is skipped cleanly.
    """

    def embed(self, text: str) -> list[float]:
        raise EmbeddingServiceError('Embedding service is not configured')


class HttpEmbeddingProvider:
    """Send embedding requests to an OpenAI-compatible embeddings endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = '',
        model: str = '',
        timeout_seconds: float = DEFAULT_EMBEDDING_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip('/')
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for ``text``.

        Raises:
            EmbeddingServiceError: On any network, HTTP, or parsing error.
        """
        headers = {'Content-Type': 'application/json'}
        if self._api_key:
            headers['Authorization'] = f'Bearer {self._api_key}'

        payload: dict[str, Any] = {'input': text}
        if self._model:
            payload['model'] = self._model

        try:
            with httpx.Client(timeout=self._timeout_seconds) as client:
                response = client.post(
                    f'{self._base_url}/embeddings',
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
            embedding = data['data'][0]['embedding']
            return [float(value) for value in cast('list[Any]', embedding)]
        except Exception as err:
            raise EmbeddingServiceError(str(err)) from err


__all__ = [
    'EmbeddingProvider',
    'EmbeddingServiceError',
    'HttpEmbeddingProvider',
    'NoopEmbeddingProvider',
]
