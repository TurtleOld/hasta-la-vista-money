"""Middleware for injecting CSP nonce into static asset tags in HTML responses."""

import html
import re


class CompressorNonceMiddleware:
    """Add CSP nonce to `<link>` and `<script>` tags that reference static assets.

    The middleware looks for tags with `href`/`src` pointing to `/static/*.css` and
    `/static/*.js` in HTML responses and injects a `nonce` attribute using the value
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
            A quoted attribute value (e.g., '"abc123"') or an empty string if invalid.
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

    def process_response(self, request, response):
        """Inject nonce into qualifying tags for HTML responses.

        Args:
            request: Django HttpRequest that may contain `csp_nonce`.
            response: Django HttpResponse to potentially modify.

        Returns:
            The original response if not HTML or nonce is missing/invalid.
            Otherwise, a response with `nonce` added to matching `<link>` and
            `<script>` tags that reference static assets.
        """
        nonce = getattr(request, 'csp_nonce', None)
        if not nonce:
            return response

        safe_nonce = self._escape_nonce(nonce)
        if not safe_nonce:
            return response

        ctype = response.get('Content-Type', '')
        if not ctype.startswith('text/html'):
            return response

        charset = getattr(response, 'charset', None) or 'utf-8'
        try:
            content = response.content.decode(charset, errors='ignore')
        except Exception:
            return response

        def add_nonce(match: re.Match) -> str:
            tag = match.group(0)
            if self._HAS_NONCE_RE.search(tag):
                return tag
            return self._inject_attr(tag, f'nonce={safe_nonce}')

        content = self._LINK_RE.sub(add_nonce, content)
        content = self._SCRIPT_RE.sub(add_nonce, content)

        new_bytes = content.encode(charset, errors='ignore')
        response.content = new_bytes
        if 'Content-Length' in response:
            response['Content-Length'] = str(len(new_bytes))

        return response
