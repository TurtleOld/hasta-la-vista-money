"""Типизация для расширенных типов Django."""

from typing import TYPE_CHECKING

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest

if TYPE_CHECKING:
    from config.containers import ApplicationContainer


class RequestWithContainer(HttpRequest):
    """HttpRequest с добавленным атрибутом container."""

    container: 'ApplicationContainer'


class WSGIRequestWithContainer(WSGIRequest):
    """WSGIRequest с добавленным атрибутом container."""

    container: 'ApplicationContainer'
