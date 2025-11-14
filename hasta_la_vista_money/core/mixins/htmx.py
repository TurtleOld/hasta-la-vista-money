from typing import Any, Protocol, cast

from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse


class TemplateResponseMixinProtocol(Protocol):
    """Protocol for views with template response methods."""

    def get_template_names(self) -> list[str]: ...

    def render_to_response(
        self,
        context: dict[str, Any],
        **response_kwargs: Any,
    ) -> HttpResponse: ...


class HTMXMixin:
    htmx_template_name: str | None = None

    def is_htmx(self, request: HttpRequest) -> bool:
        return request.headers.get('HX-Request') == 'true'

    def get_template_names(self) -> list[str]:
        if (
            hasattr(self, 'request')
            and self.is_htmx(self.request)
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
        if (
            hasattr(self, 'request')
            and self.is_htmx(self.request)
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
        return ''
