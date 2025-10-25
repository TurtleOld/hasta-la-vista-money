"""Middleware for injecting CSP nonce into static asset tags
in HTML responses."""

import html
import re


class CompressorNonceMiddleware:
    """Add CSP nonce to `<link>` and `<script>` tags that reference
    static assets.

    The middleware looks for tags with `href`/`src` pointing to
    `/static/*.css` and
    `/static/*.js` in HTML responses and injects a `nonce` attribute
    using the value
    from `request.csp_nonce` after strict validation and safe quoting.
    """

    _NONCE_RE = re.compile(r'^[A-Za-z0-9+/_-]{1,128}={0,2}$')
    _LINK_RE = re.compile(
        r'<link\b(?=[^>]*\bhref="[^"]*/static/[^"]*\.css[^"]*")[^>]*?/?>',
        re.IGNORECASE,
    )
    _SCRIPT_RE = re.compile(
        r'<script\b(?=[^>]*\bsrc="[^"]*/static/[^"]*\.js[^"]*")[^>]*?/?>',
        re.IGNORECASE,
    )
    _HAS_NONCE_RE = re.compile(r'\bnonce\s*=', re.IGNORECASE)

    def __init__(self, get_response):
        """Initialize middleware.

        Args:
            get_response: The next middleware or view callable.
        """
        self.get_response = get_response

    def __call__(self, request):
        """Process request/response chain.

        Args:
            request: Django HttpRequest.

        Returns:
            Django HttpResponse.
        """
        response = self.get_response(request)
        return self.process_response(request, response)

    def _validate_nonce(self, nonce) -> bool:
        """Validate nonce characters and length.

        Args:
            nonce: Nonce value to validate.

        Returns:
            True if the nonce matches the allowed pattern; otherwise False.
        """
        if not nonce:
            return False
        return bool(self._NONCE_RE.match(str(nonce)))

    def _quote_attr_value(self, value: str) -> str:
        """Return an HTML-attribute-safe quoted value.

        Args:
            value: Raw attribute value.

        Returns:
            Value wrapped in double quotes with special characters escaped.
        """
        return '"' + html.escape(value, quote=True) + '"'

    def _escape_nonce(self, nonce) -> str:
        """Produce a safely quoted HTML-attribute value for the nonce.

        Args:
            nonce: Nonce value to escape.

        Returns:
            A quoted attribute value (e.g., '"abc123"') or an empty string
            if invalid.
        """
        if not self._validate_nonce(nonce):
            return ''
        return self._quote_attr_value(str(nonce))

    def _inject_attr(self, tag: str, safe_attr: str) -> str:
        """Insert an attribute into a start tag before the closing bracket.

        Handles both `>` and `/>` endings.

        Args:
            tag: Full start tag as a string.
            safe_attr: Attribute string like 'nonce="..."'.

        Returns:
            Modified tag with the attribute inserted.
        """
        if tag.endswith('/>'):
            return f'{tag[:-2]} {safe_attr}/>'
        return f'{tag[:-1]} {safe_attr}>'

    def _validate_nonce(self, request) -> str | None:
        """Validate and get nonce from request."""
        nonce = getattr(request, 'csp_nonce', None)
        if not nonce:
            return None

        safe_nonce = self._escape_nonce(nonce)
        return safe_nonce if safe_nonce else None

    def _is_html_response(self, response) -> bool:
        """Check if response is HTML content."""
        ctype = response.get('Content-Type', '')
        return ctype.startswith('text/html')

    def _decode_response_content(self, response) -> str | None:
        """Decode response content safely."""
        charset = getattr(response, 'charset', None) or 'utf-8'
        try:
            return response.content.decode(charset, errors='ignore')
        except (UnicodeDecodeError, AttributeError):
            return None

    def _add_nonce_to_content(self, content: str, safe_nonce: str) -> str:
        """Add nonce to content using regex substitution."""

        def add_nonce(match: re.Match) -> str:
            tag = match.group(0)
            if self._HAS_NONCE_RE.search(tag):
                return tag
            return self._inject_attr(tag, f'nonce={safe_nonce}')

        content = self._LINK_RE.sub(add_nonce, content)
        return self._SCRIPT_RE.sub(add_nonce, content)

    def _update_response_content(self, response, content: str) -> None:
        """Update response content and headers."""
        charset = getattr(response, 'charset', None) or 'utf-8'
        new_bytes = content.encode(charset, errors='ignore')
        response.content = new_bytes

        if 'Content-Length' in response:
            response['Content-Length'] = str(len(new_bytes))

    def process_response(self, request, response):
        """Inject nonce into qualifying tags for HTML responses."""
        safe_nonce = self._validate_nonce(request)
        if not safe_nonce:
            return response

        if not self._is_html_response(response):
            return response

        content = self._decode_response_content(response)
        if content is None:
            return response

        content = self._add_nonce_to_content(content, safe_nonce)
        self._update_response_content(response, content)

        return response
