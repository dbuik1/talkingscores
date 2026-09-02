from django.conf import settings


class ProductionSecurityHeadersMiddleware:
    """Adds the content security policy on every response outside debug mode."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not settings.DEBUG:
            response.setdefault("Content-Security-Policy", settings.CONTENT_SECURITY_POLICY)
        return response
