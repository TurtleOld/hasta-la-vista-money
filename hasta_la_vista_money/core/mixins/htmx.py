from typing import Any

from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse


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
        return super().get_template_names()  # type: ignore[misc]

    def render_to_response(
        self,
        context: dict[str, Any],
        **response_kwargs: Any,
    ) -> HttpResponse:
        if hasattr(self, 'request') and self.is_htmx(self.request):
            response = super().render_to_response(context, **response_kwargs)  # type: ignore[misc]
            if isinstance(response, TemplateResponse):
                response['HX-Trigger'] = self.get_htmx_trigger_events()
            return response
        return super().render_to_response(context, **response_kwargs)  # type: ignore[misc]

    def get_htmx_trigger_events(self) -> str:
        return ''
