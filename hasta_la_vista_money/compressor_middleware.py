import re
import html


class CompressorNonceMiddleware:
    """Middleware that adds CSP nonce to static CSS and JS files in HTML responses."""

    def __init__(self, get_response):
        """Initialize the middleware.
        
        Args:
            get_response: The next middleware in the chain.
        """
        self.get_response = get_response

    def __call__(self, request):
        """Process the request and add nonce to static files.
        
        Args:
            request: The HTTP request object.
            
        Returns:
            The HTTP response with nonce added to static files.
        """
        response = self.get_response(request)
        return self.process_response(request, response)

    def _validate_nonce(self, nonce):
        """Check if nonce contains only safe characters for HTML attributes.
        
        Args:
            nonce: The nonce string to validate.
            
        Returns:
            True if nonce is valid, False otherwise.
        """
        if not nonce:
            return False
        nonce_str = str(nonce)
        return bool(re.match(r'^[A-Za-z0-9_-]+$', nonce_str))

    def _escape_nonce(self, nonce):
        """Escape nonce for safe use in HTML attributes.
        
        Args:
            nonce: The nonce string to escape.
            
        Returns:
            Escaped nonce string or empty string if invalid.
        """
        if not self._validate_nonce(nonce):
            return ''
        nonce_str = str(nonce)
        return html.escape(nonce_str, quote=True)

    def process_response(self, request, response):
        """Add nonce to static CSS and JS files in HTML content.
        
        Args:
            request: The HTTP request object.
            response: The HTTP response object.
            
        Returns:
            The modified response with nonce added to static files.
        """
        if not hasattr(request, 'csp_nonce') or not request.csp_nonce:
            return response

        safe_nonce = self._escape_nonce(request.csp_nonce)
        if not safe_nonce:
            return response

        if response.get('Content-Type', '').startswith('text/html'):
            content = response.content.decode('utf-8')

            css_pattern = r'<link([^>]*href="[^"]*\/static\/[^"]*\.css"[^>]*)>'
            content = re.sub(
                css_pattern,
                lambda m: f'<link{html.escape(m.group(1), quote=True)} nonce="{safe_nonce}">'
                if 'nonce=' not in m.group(0)
                else m.group(0),
                content,
            )

            js_pattern = r'<script([^>]*src="[^"]*\/static\/[^"]*\.js"[^>]*)>'
            content = re.sub(
                js_pattern,
                lambda m: f'<script{html.escape(m.group(1), quote=True)} nonce="{safe_nonce}">'
                if 'nonce=' not in m.group(0)
                else m.group(0),
                content,
            )

            response.content = content.encode('utf-8')

        return response
