from django.conf import settings


class ProductionSecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not settings.DEBUG:
            response.setdefault("Content-Security-Policy", "upgrade-insecure-requests")
        return response
