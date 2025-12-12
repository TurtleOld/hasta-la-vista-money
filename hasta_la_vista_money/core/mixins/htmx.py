"""HTMX mixin for Django views.

This module provides mixins for handling HTMX requests in Django views,
including template switching and trigger events.
"""

from typing import Any, Protocol, cast

from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse


class TemplateResponseMixinProtocol(Protocol):
    """Protocol for views with template response methods.

    Defines the interface for views that can render templates
    and return template responses.
    """

    def get_template_names(self) -> list[str]: ...

    def render_to_response(
        self,
        context: dict[str, Any],
        **response_kwargs: Any,
    ) -> HttpResponse: ...


class HTMXMixin:
    """Mixin for handling HTMX requests in Django views.

    Provides functionality to detect HTMX requests and switch templates
    accordingly, as well as trigger HTMX events in responses.

    Attributes:
        htmx_template_name: Optional template name to use for HTMX requests.
    """

    htmx_template_name: str | None = None

    def is_htmx(self, request: HttpRequest) -> bool:
        """Check if request is an HTMX request.

        Args:
            request: HTTP request object.

        Returns:
            bool: True if request is from HTMX, False otherwise.
        """
        return request.headers.get('HX-Request') == 'true'

    def get_template_names(self) -> list[str]:
        request = getattr(self, 'request', None)
        if (
            request is not None
            and self.is_htmx(request)
            and self.htmx_template_name
        ):
            return [self.htmx_template_name]
        if hasattr(super(), 'get_template_names'):
            mixin_self = cast('TemplateResponseMixinProtocol', self)
            return mixin_self.get_template_names()
        return []

    def render_to_response(
        self,
        context: dict[str, Any],
        **response_kwargs: Any,
    ) -> HttpResponse:
        request = getattr(self, 'request', None)
        if (
            request is not None
            and self.is_htmx(request)
            and hasattr(super(), 'render_to_response')
        ):
            mixin_self = cast('TemplateResponseMixinProtocol', self)
            response = mixin_self.render_to_response(context, **response_kwargs)
            if isinstance(response, TemplateResponse):
                response['HX-Trigger'] = self.get_htmx_trigger_events()
            return response
        if hasattr(super(), 'render_to_response'):
            mixin_self = cast('TemplateResponseMixinProtocol', self)
            return mixin_self.render_to_response(context, **response_kwargs)
        return HttpResponse()

    def get_htmx_trigger_events(self) -> str:
        """Get HTMX trigger events string.

        Override this method to return custom HTMX trigger events
        that should be added to the response.

        Returns:
            str: JSON string with HTMX trigger events.
        """
        return ''
