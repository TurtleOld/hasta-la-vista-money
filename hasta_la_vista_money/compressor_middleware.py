import re


class CompressorNonceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return self.process_response(request, response)

    def process_response(self, request, response):
        if not hasattr(request, 'csp_nonce') or not request.csp_nonce:
            return response

        if response.get('Content-Type', '').startswith('text/html'):
            content = response.content.decode('utf-8')

            css_pattern = r'<link([^>]*href="[^"]*\/static\/[^"]*\.css"[^>]*)>'
            content = re.sub(
                css_pattern,
                lambda m: f'<link{m.group(1)} nonce="{request.csp_nonce}">'
                if 'nonce=' not in m.group(0)
                else m.group(0),
                content,
            )

            js_pattern = r'<script([^>]*src="[^"]*\/static\/[^"]*\.js"[^>]*)>'
            content = re.sub(
                js_pattern,
                lambda m: f'<script{m.group(1)} nonce="{request.csp_nonce}">'
                if 'nonce=' not in m.group(0)
                else m.group(0),
                content,
            )

            response.content = content.encode('utf-8')

        return response
