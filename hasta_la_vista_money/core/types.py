"""Type definitions for extended Django types.

This module provides type definitions for Django request objects
with dependency injection container support.
"""

from typing import TYPE_CHECKING

from django.core.handlers.wsgi import WSGIRequest
from django.http import HttpRequest

if TYPE_CHECKING:
    from config.containers import ApplicationContainer


class RequestWithContainer(HttpRequest):
    """HttpRequest with added container attribute.

    Extends Django's HttpRequest to include a dependency injection
    container for accessing services.

    Attributes:
        container: ApplicationContainer instance for dependency injection.
    """

    container: 'ApplicationContainer'


class WSGIRequestWithContainer(WSGIRequest):
    """WSGIRequest with added container attribute.

    Extends Django's WSGIRequest to include a dependency injection
    container for accessing services.

    Attributes:
        container: ApplicationContainer instance for dependency injection.
    """

    container: 'ApplicationContainer'
