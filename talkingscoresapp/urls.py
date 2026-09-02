from django.urls import path, register_converter
from django.views.generic.base import TemplateView
from . import views


class ScoreIdConverter:
    """A score id is the lower-case hex SHA-256 of the uploaded file, so anything else is not a score."""

    regex = "[0-9a-f]{64}"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


register_converter(ScoreIdConverter, "scoreid")

urlpatterns = [
    path('', views.index, name='index'),
    path('change-log', views.change_log, name='change-log'),
    path('contact-us', views.contact_us, name='contact-us'),
    path('privacy-policy', views.privacy_policy, name='privacy-policy'),
    path('score/<scoreid:id>/<filename>', views.score, name='score'),
    path('score_options/<scoreid:id>/<filename>', views.options, name='options'),
    path('process/<scoreid:id>/<filename>', views.process, name='process'),
    path('process_status/<scoreid:id>/<filename>', views.process_status, name='process-status'),
    path('oops/<scoreid:id>/<filename>', views.error, name='error'),
    path('download/html/<scoreid:id>/<filename>', views.download_html, name='download-html'),
    path('midis/<scoreid:id>/<filename>', views.midi, name='midi'),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain"), ),
    path("sitemap.xml", TemplateView.as_view(template_name="sitemap.xml", content_type="text/xml"), ),
]
