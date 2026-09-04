"""
Essential tests for Talking Scores - focused on critical issues.
"""

from django.conf import settings
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from talkingscores import settings as score_settings
from talkingscoresapp.models import TSScore
from talkingscoresapp import models as score_models
from talkingscoresapp import views as views_module
import requests
from talkingscoresapp.management.commands import cleanup_media
from jinja2 import Environment, FileSystemLoader
from unittest.mock import patch, Mock
from io import StringIO
import tempfile
import shutil
import subprocess
import glob
import os
import time
import json
import re
import runpy
import socket
import threading
import zipfile

# Score ids are the SHA-256 of the file, so tests use a well-formed 64-digit id.
VALID_ID = "a" * 64
OTHER_ID = "b" * 64
REAL_THREAD = threading.Thread
PUBLIC_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]



def reader_context(**overrides):
    """The context the score template needs, with nothing to show."""
    context = {
        "export_mode": False,
        "export_theme": None,
        "inline_css": "",
        "inline_js": "",
        "static_icon_url": "/static/img/icon.svg",
        "static_site_css_url": "/static/css/site.css",
        "static_css_url": "/static/css/score.css",
        "static_js_url": "/static/js/score.js",
        "static_player_url": "/static/js/player.js",
        "download_html_url": "/download/html/abc123/score.musicxml",
        "download_text_url": "/download/text/abc123/score.musicxml",
        "download_braille_url": "/download/braille/abc123/score.musicxml",
        "options_url": "/score_options/abc123/score.musicxml",
        "basic_information": {"title": "Score", "composer": "Composer"},
        "meta_line": ["C major", "4 4", "Piano", "8 bars"],
        "score_data": {"key": "/midis/abc123/score.musicxml", "firstBar": 1, "firstNumberedBar": 1, "lastBar": 8, "totalBars": 8,
                       "pickupBar": None, "barsPerGroup": 2, "groupSizes": [1, 2, 4, 8],
                       "midi": {"base": "/midis/abc123/score.musicxml",
                                "parts": [{"index": 0, "label": "Piano", "read": True}],
                                "voices": [{"parts": [0], "label": "Piano"}]}},
        "music_segments": [],
        "settings": {},
        "style_name": "Musical terms",
        "facts": None,
        "palette_css": "",
        "colour_root_class": "",
    }
    context.update(overrides)
    return context


class SecurityTests(TestCase):
    """Score ids and filenames from the URL never reach the filesystem unchecked."""

    def test_score_id_must_be_sha256_hex(self):
        for bad_id in ("test123", "../../etc", "A" * 64, "a" * 63, "a" * 65, "z" * 64):
            with self.assertRaises(ValueError):
                TSScore(id=bad_id, filename="score.musicxml").get_data_file_path()

    def test_score_urls_reject_malformed_ids(self):
        client = Client()
        for path in ("/score/abc123/score.musicxml", "/midis/../score.musicxml", "/process_status/%s/x.musicxml" % ("A" * 64)):
            self.assertEqual(client.get(path).status_code, 404, path)

    def test_filename_path_components_are_stripped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for malicious_name in ("../../../etc/passwd", "test/../../../secret.txt", "/etc/passwd"):
                path = TSScore(id=VALID_ID, filename=malicious_name).get_data_file_path(root=temp_dir)
                self.assertEqual(os.path.dirname(path), os.path.join(temp_dir, VALID_ID))
                self.assertNotIn("..", os.path.basename(path))

    def test_secret_key_is_required_outside_debug(self):
        settings_path = os.path.join(score_settings.BASE_DIR, "talkingscores", "settings.py")
        with patch.dict(os.environ, {"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": ""}):
            with self.assertRaises(RuntimeError):
                runpy.run_path(settings_path)
        with patch.dict(os.environ, {"DJANGO_DEBUG": "true", "DJANGO_SECRET_KEY": ""}):
            self.assertTrue(runpy.run_path(settings_path)["SECRET_KEY"])
        with patch.dict(os.environ, {"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "x" * 50}):
            self.assertFalse(runpy.run_path(settings_path)["DEBUG"])


class BasicFunctionalityTests(TestCase):
    """Tests for basic page loads."""
    
    def setUp(self):
        self.client = Client()
        
    def test_homepage_loads(self):
        """Ensure the main page works."""
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Talking Scores')

    def test_railway_hosts_are_allowed(self):
        self.assertIn(".up.railway.app", score_settings.ALLOWED_HOSTS)
        self.assertIn(".railway.app", score_settings.ALLOWED_HOSTS)
        self.assertIn("talkingscores.davidbuik.com", score_settings.ALLOWED_HOSTS)

    def test_railway_origins_are_trusted_for_csrf(self):
        self.assertIn("https://talkingscores.davidbuik.com", score_settings.CSRF_TRUSTED_ORIGINS)
        self.assertIn("https://talkingscores-production.up.railway.app", score_settings.CSRF_TRUSTED_ORIGINS)
        self.assertIn("https://*.up.railway.app", score_settings.CSRF_TRUSTED_ORIGINS)
        self.assertEqual(score_settings.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_https_security_defaults_are_configured(self):
        self.assertTrue(score_settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(score_settings.SECURE_REFERRER_POLICY, "same-origin")
        self.assertFalse(score_settings.SECURE_HSTS_PRELOAD)

    def test_static_files_are_configured_for_production(self):
        self.assertIn("whitenoise.middleware.WhiteNoiseMiddleware", score_settings.MIDDLEWARE)
        self.assertIn("talkingscores.middleware.ProductionSecurityHeadersMiddleware", score_settings.MIDDLEWARE)
        self.assertEqual(
            score_settings.STORAGES["staticfiles"]["BACKEND"],
            "whitenoise.storage.CompressedStaticFilesStorage",
        )
        self.assertTrue(score_settings.STATIC_ROOT.endswith("staticfiles"))

    @override_settings(DEBUG=False)
    def test_production_security_header_upgrades_insecure_requests(self):
        response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 200)
        # Read as whole directives: "script-src 'self'" is also a substring of a
        # policy that has since been widened to allow another host.
        directives = {}
        for directive in response["Content-Security-Policy"].split(";"):
            parts = directive.split()
            if parts:
                directives[parts[0]] = parts[1:]

        self.assertEqual(directives["script-src"], ["'self'", "'unsafe-inline'"])
        self.assertEqual(directives["frame-ancestors"], ["'none'"])
        self.assertIn("upgrade-insecure-requests", directives)
        # The page sounds its own MIDI, so it needs no other host, no worker and no media element.
        self.assertEqual(directives["connect-src"], ["'self'"])
        self.assertEqual(directives["worker-src"], ["'none'"])
        self.assertEqual(directives["media-src"], ["'none'"])
        self.assertEqual(directives["object-src"], ["'none'"])

    def test_home_page_names_the_file_it_takes_and_where_it_goes(self):
        response = self.client.get(reverse("index"))
        content = response.content.decode("utf-8")

        # The file rules sit above the control they govern, not under it.
        self.assertLess(content.index("up to 10 MB"), content.index('type="file"'))
        # The rules are attached to the control, so they are read out with it.
        self.assertIn('aria-describedby="file-rules"', content)
        self.assertIn('id="file-rules"', content)
        self.assertIn('accept=".xml,.musicxml,.mxl"', content)
        self.assertIn("Choose how it reads", content)

    def test_site_shell_reads_the_stored_colours_before_the_page_paints(self):
        response = self.client.get(reverse("index"))
        content = response.content.decode("utf-8")

        # The settings are read in the head, so the page never repaints under the reader.
        self.assertLess(content.index("talkingscores.reader"), content.index("<body>"))
        self.assertIn('href="/static/css/site.css"', content)
        self.assertIn("Skip to the main content", content)

    def test_site_shell_carries_no_bootstrap(self):
        for name in ("index", "change-log", "contact-us", "privacy-policy"):
            content = self.client.get(reverse(name)).content.decode("utf-8")
            self.assertNotIn("bootstrap", content.lower(), name)
            self.assertNotIn("navbar", content, name)

    def test_site_shell_does_not_load_external_active_scripts(self):
        response = self.client.get(reverse('index'))
        content = response.content.decode("utf-8")

        self.assertNotIn("googletagmanager.com", content)
        self.assertNotIn("bootstrap.bundle.min.js", content)
        self.assertNotIn('script src="https://', content)

    @patch("talkingscoresapp.views.logger.warning")
    @patch("talkingscoresapp.views.os.listdir", side_effect=OSError("missing"))
    def test_homepage_loads_when_example_scores_unavailable(self, mock_listdir, mock_logger_warning):
        response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Talking Scores')
        # Nothing to try, so nothing offers it.
        self.assertNotContains(response, 'Try an example score')
        mock_logger_warning.assert_called_once()

    @patch("talkingscoresapp.views.os.listdir")
    def test_example_scores_are_filtered_and_sorted(self, mock_listdir):
        from talkingscoresapp.views import get_example_scores

        mock_listdir.return_value = ["z.html", "notes.txt", "a.html"]

        self.assertEqual(get_example_scores(), ["a.html", "z.html"])
        
    def test_change_log_loads(self):
        """Test the change log page loads correctly."""
        response = self.client.get(reverse('change-log'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Change log')

    def test_contact_us_loads(self):
        """Test the contact us page loads correctly."""
        response = self.client.get(reverse('contact-us'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'talkingscores@gmail.com')

    def test_privacy_page_describes_what_the_site_actually_stores(self):
        """The page names the cookies that are set, so it has to track the code."""
        response = self.client.get(reverse('privacy-policy'))
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("What is kept and for how long", content)
        for cookie in ("csrftoken", "messages"):
            self.assertIn(cookie, content)
        self.assertNotIn("Google Analytics", content)

    def test_no_page_claims_an_analytics_cookie_that_is_never_set(self):
        """Nothing on the site loads analytics, so no cookie of that name exists."""
        for name in ("index", "privacy-policy", "contact-us"):
            content = self.client.get(reverse(name)).content.decode("utf-8")
            for cookie in ("_ga", "_gid", "_gat_gtag_"):
                self.assertNotIn(cookie, content, name)

    @patch("talkingscoresapp.views.TSScore.start_background_processing", return_value=True)
    @patch("talkingscoresapp.views.TSScore.state", return_value="processed")
    def test_processing_page_shows_live_status_region(self, mock_state, mock_start):
        response = self.client.get(
            reverse("process", kwargs={"id": VALID_ID, "filename": "score.musicxml"})
        )

        self.assertEqual(response.status_code, 200)
        # role="status" is a polite live region in its own right.
        self.assertContains(response, 'role="status"')
        self.assertContains(response, "Starting to read the file")
        mock_start.assert_called_once()

    @patch("talkingscoresapp.views.TSScore.state", return_value="fetching")
    def test_processing_page_sends_a_missing_score_home(self, mock_state):
        response = self.client.get(
            reverse("process", kwargs={"id": VALID_ID, "filename": "score.musicxml"}), follow=True
        )

        self.assertRedirects(response, reverse("index"))
        self.assertContains(response, "Upload the file again")

    @patch("talkingscoresapp.views.TSScore.state", return_value="fetching")
    def test_process_status_reports_a_missing_score(self, mock_state):
        response = self.client.get(
            reverse("process-status", kwargs={"id": VALID_ID, "filename": "score.musicxml"})
        )

        self.assertEqual(response.json()["status"], "missing")
        self.assertEqual(response.json()["next_url"], reverse("index"))

    @patch("talkingscoresapp.views.TSScore.generation_is_live", return_value=False)
    @patch("talkingscoresapp.views.TSScore.start_background_processing", return_value=True)
    @patch("talkingscoresapp.views.TSScore.processing_status")
    @patch("talkingscoresapp.views.TSScore.state", return_value="processed")
    def test_process_status_restarts_a_dead_run(self, mock_state, mock_status, mock_start, mock_live):
        mock_status.side_effect = [
            {"status": "processing", "message": "Generating score."},
            {"status": "processing", "message": "Generating score."},
        ]

        self.client.get(reverse("process-status", kwargs={"id": VALID_ID, "filename": "score.musicxml"}))

        mock_start.assert_called_once()

    @patch("talkingscoresapp.views.TSScore.generation_is_live", return_value=True)
    @patch("talkingscoresapp.views.TSScore.start_background_processing", return_value=True)
    @patch("talkingscoresapp.views.TSScore.processing_status", return_value={"status": "processing", "message": "Generating score."})
    @patch("talkingscoresapp.views.TSScore.state", return_value="processed")
    def test_process_status_leaves_a_live_run_alone(self, mock_state, mock_status, mock_start, mock_live):
        self.client.get(reverse("process-status", kwargs={"id": VALID_ID, "filename": "score.musicxml"}))

        mock_start.assert_not_called()


class ErrorPageTests(TestCase):
    def test_error_page_names_the_next_step(self):
        response = Client().get(reverse("error", kwargs={"id": VALID_ID, "filename": "score.musicxml"}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Open a different score")
        self.assertNotContains(response, "<form")


class SubmissionFormTests(TestCase):
    def test_submission_form_accepts_small_musicxml_upload(self):
        from talkingscoresapp.views import MusicXMLSubmissionForm

        upload = SimpleUploadedFile("score.musicxml", b"<score-partwise></score-partwise>")
        form = MusicXMLSubmissionForm(files={"filename": upload})

        self.assertTrue(form.is_valid(), form.errors)

    @patch("talkingscoresapp.views.MAX_UPLOADED_SCORE_BYTES", 5)
    def test_submission_form_rejects_large_musicxml_upload(self):
        from talkingscoresapp.views import MusicXMLSubmissionForm

        upload = SimpleUploadedFile("score.musicxml", b"123456")
        form = MusicXMLSubmissionForm(files={"filename": upload})

        self.assertFalse(form.is_valid())
        self.assertIn("filename", form.errors)
        self.assertIn("too large", form.errors["filename"][0])

    def test_a_rejected_file_is_named_once(self):
        from talkingscoresapp.views import MusicXMLSubmissionForm

        upload = SimpleUploadedFile("score.pdf", b"%PDF-1.4")
        form = MusicXMLSubmissionForm(files={"filename": upload})

        self.assertFalse(form.is_valid())
        # Saying the file is the wrong type and that no file was given at all
        # would leave the reader with two contradictory things to fix.
        self.assertEqual(form.errors, {"filename": [
            "Choose a MusicXML file. The name has to end in .musicxml, .xml or .mxl."]})

    def test_submission_form_accepts_musicxml_url_with_query_string(self):
        from talkingscoresapp.views import MusicXMLSubmissionForm

        form = MusicXMLSubmissionForm(data={"url": "https://example.com/score.musicxml?download=1"})

        self.assertTrue(form.is_valid(), form.errors)

    def test_submission_form_rejects_non_musicxml_url(self):
        from talkingscoresapp.views import MusicXMLSubmissionForm

        form = MusicXMLSubmissionForm(data={"url": "https://example.com/score.pdf"})

        self.assertFalse(form.is_valid())
        self.assertIn("url", form.errors)
        self.assertIn(".xml", form.errors["url"][0])


class FileWriteTests(TestCase):
    def test_write_json_file_atomic_creates_readable_file(self):
        from talkingscoresapp.views import write_json_file_atomic

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "nested", "score.opts")

            write_json_file_atomic(json_path, {"bars_at_a_time": 2})

            with open(json_path, "r", encoding="utf-8") as json_file:
                self.assertEqual(json.load(json_file), {"bars_at_a_time": 2})

    @patch("talkingscoresapp.views.os.replace", side_effect=OSError("replace failed"))
    def test_write_json_file_atomic_removes_temp_file_on_replace_failure(self, mock_replace):
        from talkingscoresapp.views import write_json_file_atomic

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = os.path.join(temp_dir, "nested", "score.opts")

            with self.assertRaises(OSError):
                write_json_file_atomic(json_path, {"bars_at_a_time": 2})

            temp_path = mock_replace.call_args.args[0]
            self.assertFalse(os.path.exists(temp_path))


class DownloadTests(TestCase):
    """Tests for local save and MIDI download behavior."""

    def setUp(self):
        self.client = Client()

    @patch("talkingscoresapp.views.MidiHandler.get_or_make_midi_file")
    def test_midi_response_headers(self, mock_get_midi):
        # The saved name is read off the file that was written, so the stand-in is
        # named the way the handler names one.
        midi_dir = tempfile.mkdtemp()
        midi_path = os.path.join(midi_dir, "score.musicxmls3e7.mid")
        with open(midi_path, "wb") as midi_file:
            midi_file.write(b"MThd")

        mock_get_midi.return_value = midi_path

        try:
            response = self.client.get(
                reverse("midi", kwargs={"id": VALID_ID, "filename": "score.musicxml"}) + "?start=3&end=7"
            )
        finally:
            if "response" in locals():
                response.close()
            shutil.rmtree(midi_dir, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("audio/midi", response["Content-Type"])
        self.assertIn("score-bars-3-to-7.mid", response["Content-Disposition"])
        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_saved_midi_files_are_named_for_the_bars_they_hold(self):
        self.assertEqual(views_module.saved_midi_name("bach.musicxml", "/m/bach.musicxmls1e2.mid"),
                         "bach-bars-1-to-2.mid")
        self.assertEqual(views_module.saved_midi_name("bach.musicxml", "/m/bach.musicxmls4e4.mid"),
                         "bach-bar-4.mid")
        self.assertEqual(views_module.saved_midi_name("bach.musicxml", "/m/bach.musicxmls0e0.mid"),
                         "bach-pickup-bar.mid")

    def test_a_saved_midi_file_is_named_for_the_bars_written_not_the_bars_asked_for(self):
        # A request reaching past the score is written as the bars that exist, and the
        # name follows the file so it never claims bars it does not hold.
        self.assertEqual(views_module.saved_midi_name("bach.musicxml", "/m/bach.musicxmls5e9.mid"),
                         "bach-bars-5-to-9.mid")
        self.assertEqual(views_module.saved_midi_name("bach.musicxml", "/m/unreadable"),
                         "bach.mid")

    @patch("talkingscoresapp.views.MidiHandler.get_or_make_midi_file")
    def test_midi_rejects_missing_required_query_params(self, mock_get_midi):
        response = self.client.get(
            reverse("midi", kwargs={"id": VALID_ID, "filename": "score.musicxml"})
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Missing MIDI parameter", status_code=400)
        mock_get_midi.assert_not_called()

    @patch("talkingscoresapp.views.MidiHandler.get_or_make_midi_file")
    def test_midi_rejects_invalid_query_params(self, mock_get_midi):
        invalid_urls = [
            "?start=x&end=7",
            "?start=8&end=4",
            "?start=-1&end=7",
            "?start=3&end=",
            "?end=7",                    # start is missing
            "?start=3",                  # end is missing
            "?start=1&end=999999999",    # past the largest bar number a score can hold
            "?start=1&end=1000",         # more bars than one press of play ever asks for
        ]

        for query_string in invalid_urls:
            response = self.client.get(
                reverse("midi", kwargs={"id": VALID_ID, "filename": "score.musicxml"}) + query_string
            )
            self.assertEqual(response.status_code, 400)

        mock_get_midi.assert_not_called()

    @patch("talkingscoresapp.views.TSScore.state")
    @patch("talkingscoresapp.views.TSScore.html")
    def test_html_download(self, mock_html, mock_state):
        mock_state.return_value = "processed"
        mock_html.return_value = "<html><body>Score</body></html>"

        response = self.client.get(
            reverse("download-html", kwargs={"id": VALID_ID, "filename": "score.musicxml"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn("score-talking-score.html", response["Content-Disposition"])
        self.assertContains(response, "Score")
        mock_html.assert_called_once_with(export_theme=None, export_mode=True, raise_errors=True)

    @patch("talkingscoresapp.views.TSScore.state")
    @patch("talkingscoresapp.views.TSScore.html")
    def test_html_download_passes_valid_theme(self, mock_html, mock_state):
        mock_state.return_value = "processed"
        mock_html.return_value = "<html><body>Score</body></html>"

        response = self.client.get(
            reverse("download-html", kwargs={"id": VALID_ID, "filename": "score.musicxml"}) + "?theme=dark"
        )

        self.assertEqual(response.status_code, 200)
        mock_html.assert_called_once_with(export_theme="dark", export_mode=True, raise_errors=True)

    @patch("talkingscoresapp.views.TSScore.state")
    @patch("talkingscoresapp.views.TSScore.html")
    def test_html_download_discards_invalid_theme(self, mock_html, mock_state):
        mock_state.return_value = "processed"
        mock_html.return_value = "<html><body>Score</body></html>"

        response = self.client.get(
            reverse("download-html", kwargs={"id": VALID_ID, "filename": "score.musicxml"}) + "?theme=bad"
        )

        self.assertEqual(response.status_code, 200)
        mock_html.assert_called_once_with(export_theme=None, export_mode=True, raise_errors=True)

    def test_export_template_omits_download_and_midi_controls(self):
        env = Environment(loader=FileSystemLoader(os.path.join(os.getcwd(), "lib")))
        template = env.get_template("talkingscore.html")

        html = template.render(reader_context(
            export_mode=True, export_theme="dark", inline_js="/* reader */",
            download_html_url="", download_text_url="", download_braille_url="", options_url="",
            score_data={"key": "Score", "firstBar": 1, "firstNumberedBar": 1, "lastBar": 8, "totalBars": 8, "pickupBar": None,
                        "barsPerGroup": 2, "groupSizes": [1, 2, 4, 8], "midi": None},
        ))

        self.assertNotIn("midijs.net", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("<link ", html)
        self.assertNotIn("/download/", html)
        self.assertNotIn("/score_options/", html)
        self.assertNotIn('id="play-group"', html)
        self.assertIn('<html lang="en-GB" data-theme="dark">', html)
        self.assertIn("/* reader */", html)
        self.assertIn("Print every bar", html)
    def test_export_template_can_inline_css(self):
        env = Environment(loader=FileSystemLoader(os.path.join(os.getcwd(), "lib")))
        template = env.get_template("talkingscore.html")

        html = template.render(reader_context(
            export_mode=True, export_theme="light", inline_css="body { color: red; }",
        ))

        self.assertIn("body { color: red; }", html)
        self.assertNotIn("static/css/score.css", html)
    def test_live_template_uses_static_css_path(self):
        env = Environment(loader=FileSystemLoader(os.path.join(os.getcwd(), "lib")))
        template = env.get_template("talkingscore.html")

        html = template.render(reader_context())

        self.assertIn('href="/static/css/site.css"', html)
        self.assertIn('href="/static/img/icon.svg"', html)
        self.assertIn('href="/static/css/score.css"', html)
        self.assertIn('src="/static/js/score.js"', html)
        self.assertIn('src="/static/js/player.js"', html)
        self.assertNotIn("127.0.0.1", html)
    @patch("talkingscoresapp.views.TSScore.state")
    @patch("talkingscoresapp.views.TSScore.start_background_processing")
    @patch("talkingscoresapp.views.TSScore.processing_status")
    def test_process_status_starts_pending_processed_score(self, mock_status, mock_start, mock_state):
        mock_status.side_effect = [
            {"status": "pending", "message": ""},
            {"status": "processing", "message": "Generating score."},
        ]
        mock_state.return_value = "processed"

        response = self.client.get(
            reverse("process-status", kwargs={"id": VALID_ID, "filename": "score.musicxml"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processing")
        mock_start.assert_called_once()

    @patch("talkingscoresapp.views.TSScore.info")
    @patch("talkingscoresapp.views.TSScore.get_data_file_path")
    @patch("talkingscoresapp.views.TSScore.clear_generated_html_state")
    @patch("talkingscoresapp.views.logger.info")
    def test_options_post_clears_generated_html_state(self, mock_logger_info, mock_clear, mock_data_path, mock_info):
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_data_path.return_value = os.path.join(temp_dir, "score.musicxml")
            mock_info.return_value = {
                "title": "Score",
                "composer": "Composer",
                "instruments": ["Piano"],
                "rhythm_range": [],
                "beat_division_options": [],
            }

            response = self.client.post(
                reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"}),
                {
                    "instruments": ["1"],
                    "bars_at_a_time": "2",
                    "beat_division": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("process", kwargs={"id": VALID_ID, "filename": "score.musicxml"}))
        mock_clear.assert_called_once()

    @patch("talkingscoresapp.views.TSScore.info")
    @patch("talkingscoresapp.views.TSScore.get_data_file_path")
    @patch("talkingscoresapp.views.TSScore.clear_generated_html_state")
    @patch("talkingscoresapp.views.logger.info")
    def test_every_control_the_set_up_page_offers_reaches_the_stored_options(
            self, mock_logger_info, mock_clear, mock_data_path, mock_info):
        """The page is the only description of the form, so submitting what it
        renders has to produce a complete set of options. A control dropped from
        the template would otherwise go unnoticed until a reading came out wrong."""
        info = {
            "title": "Score",
            "composer": "Composer",
            "instruments": ["Flute", "Cello"],
            "rhythm_range": ["crotchet", "quaver"],
            "beat_division_options": ["1", "2", "4"],
            "octave_range": ["4", "5"],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = os.path.join(temp_dir, "score.musicxml")
            mock_data_path.return_value = data_path
            mock_info.return_value = info

            url = reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"})
            content = self.client.get(url).content.decode("utf-8")
            posted = self._submitted_defaults(content)

            # Nothing is typed in: the page's own defaults are what a reader sends.
            response = self.client.post(url, posted)
            self.assertEqual(response.status_code, 302)

            with open(data_path + ".opts") as options_file:
                stored = json.load(options_file)

        self.assertEqual(stored["style"], "standard")
        self.assertEqual(stored["instruments"], [1, 2])
        for key in ("bars_at_a_time", "beat_division", "pitch_description", "rhythm_description",
                    "octave_description", "octave_position", "dot_position", "accidental_style",
                    "repetition_mode", "colour_position", "key_signature_accidentals",
                    "figureNoteColours"):
            self.assertIn(key, stored)
        self.assertEqual(len(stored["figureNoteColours"]), 7)

    @staticmethod
    def _submitted_defaults(html):
        """What a browser would send from the rendered page with nothing changed."""
        posted = {}
        for tag in re.findall(r"<(?:input|select|option)\b[^>]*>", html):
            name = re.search(r'name="([^"]+)"', tag)
            value = re.search(r'value="([^"]*)"', tag)
            if tag.startswith("<select"):
                current_select = name.group(1) if name else None
                posted.setdefault(current_select, None)
                continue
            if not name:
                continue
            kind = re.search(r'type="([^"]+)"', tag)
            kind = kind.group(1) if kind else "text"
            if kind in ("checkbox", "radio") and "checked" not in tag:
                continue
            if kind == "checkbox" and name.group(1) == "instruments":
                posted.setdefault(name.group(1), []).append(value.group(1))
                continue
            posted[name.group(1)] = value.group(1) if value else "on"

        # A select posts its selected option, or its first when none is marked.
        for block in re.findall(r"<select\b[^>]*>.*?</select>", html, re.S):
            name = re.search(r'name="([^"]+)"', block)
            if not name:
                continue
            options = re.findall(r'<option value="([^"]*)"([^>]*)>', block)
            if not options:
                posted.pop(name.group(1), None)
                continue
            chosen = next((v for v, rest in options if "selected" in rest), options[0][0])
            posted[name.group(1)] = chosen
        return {key: value for key, value in posted.items() if value is not None}

    @patch("talkingscoresapp.views.TSScore.info")
    @patch("talkingscoresapp.views.TSScore.get_data_file_path")
    @patch("talkingscoresapp.views.TSScore.clear_generated_html_state")
    @patch("talkingscoresapp.views.logger.info")
    def test_options_post_rejects_invalid_instrument_selection(self, mock_logger_info, mock_clear, mock_data_path, mock_info):
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_data_path.return_value = os.path.join(temp_dir, "score.musicxml")
            mock_info.return_value = {
                "title": "Score",
                "composer": "Composer",
                "instruments": ["Piano"],
                "rhythm_range": [],
                "beat_division_options": [],
            }

            response = self.client.post(
                reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"}),
                {
                    "instruments": ["99"],
                    "bars_at_a_time": "2",
                    "beat_division": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid instrument selection")
        mock_clear.assert_not_called()

    @patch("talkingscoresapp.views.TSScore.info")
    @patch("talkingscoresapp.views.TSScore.get_data_file_path")
    @patch("talkingscoresapp.views.TSScore.clear_generated_html_state")
    @patch("talkingscoresapp.views.logger.info")
    def test_options_post_rejects_non_numeric_instrument_selection(self, mock_logger_info, mock_clear, mock_data_path, mock_info):
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_data_path.return_value = os.path.join(temp_dir, "score.musicxml")
            mock_info.return_value = {
                "title": "Score",
                "composer": "Composer",
                "instruments": ["Piano"],
                "rhythm_range": [],
                "beat_division_options": [],
            }

            response = self.client.post(
                reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"}),
                {
                    "instruments": ["not-a-number"],
                    "bars_at_a_time": "2",
                    "beat_division": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid instrument selection")
        mock_clear.assert_not_called()

    @patch("talkingscoresapp.views.TSScore.info")
    @patch("talkingscoresapp.views.TSScore.get_data_file_path")
    @patch("talkingscoresapp.views.TSScore.clear_generated_html_state")
    @patch("talkingscoresapp.views.logger.info")
    def test_options_post_rejects_invalid_bars_at_a_time(self, mock_logger_info, mock_clear, mock_data_path, mock_info):
        with tempfile.TemporaryDirectory() as temp_dir:
            mock_data_path.return_value = os.path.join(temp_dir, "score.musicxml")
            mock_info.return_value = {
                "title": "Score",
                "composer": "Composer",
                "instruments": ["Piano"],
                "rhythm_range": [],
                "beat_division_options": [],
            }

            response = self.client.post(
                reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"}),
                {
                    "instruments": ["1"],
                    "bars_at_a_time": "999",
                    "beat_division": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        # The error names the action, and links to the control it is about.
        self.assertContains(response, "Choose how many bars to read at a time")
        self.assertContains(response, 'href="#bars_at_a_time"')
        mock_clear.assert_not_called()


class CacheAndMaintenanceTests(TestCase):
    def test_score_logger_configuration_is_idempotent(self):
        handler_count = len(score_models.logger.handlers)

        score_models.configure_score_logger()

        self.assertEqual(len(score_models.logger.handlers), handler_count)

    def test_html_cache_is_reused_when_fresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score = TSScore(id=VALID_ID, filename="score.musicxml")
            data_path = score.get_data_file_path(root=temp_dir)
            os.makedirs(os.path.dirname(data_path), exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as data_file:
                data_file.write("<score-partwise></score-partwise>")
            with open(data_path + ".opts", "w", encoding="utf-8") as opts_file:
                opts_file.write("{}")
            with patch.object(score, "get_data_file_path", return_value=data_path):
                html_path = score.get_html_cache_file_path()
                with open(html_path, "w", encoding="utf-8") as html_file:
                    html_file.write("<html>cached</html>")
                now = time.time()
                os.utime(data_path, (now - 10, now - 10))
                os.utime(data_path + ".opts", (now - 10, now - 10))
                os.utime(html_path, (now, now))

                self.assertEqual(score.html(), "<html>cached</html>")

    def test_clear_generated_html_state_removes_cache_and_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score = TSScore(id=VALID_ID, filename="score.musicxml")
            data_path = os.path.join(temp_dir, VALID_ID, "score.musicxml")
            os.makedirs(os.path.dirname(data_path), exist_ok=True)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                html_path = score.get_html_cache_file_path()
                status_path = score.get_processing_status_file_path()
                with open(html_path, "w", encoding="utf-8") as html_file:
                    html_file.write("<html>stale</html>")
                with open(status_path, "w", encoding="utf-8") as status_file:
                    status_file.write('{"status": "complete"}')

                score.clear_generated_html_state()

                self.assertFalse(os.path.exists(html_path))
                self.assertFalse(os.path.exists(status_path))

    def test_processing_status_write_is_readable_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score = TSScore(id=VALID_ID, filename="score.musicxml")
            data_path = os.path.join(temp_dir, VALID_ID, "score.musicxml")
            os.makedirs(os.path.dirname(data_path), exist_ok=True)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                score._write_processing_status("processing", "Generating score.")

                status = score.processing_status()
                self.assertEqual(status["status"], "processing")
                self.assertEqual(status["message"], "Generating score.")
                self.assertIn("updated", status)

    @patch("talkingscoresapp.models.os.replace", side_effect=OSError("replace failed"))
    def test_processing_status_write_removes_temp_file_on_replace_failure(self, mock_replace):
        with tempfile.TemporaryDirectory() as temp_dir:
            score = TSScore(id=VALID_ID, filename="score.musicxml")
            data_path = os.path.join(temp_dir, VALID_ID, "score.musicxml")
            os.makedirs(os.path.dirname(data_path), exist_ok=True)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                with self.assertRaises(OSError):
                    score._write_processing_status("processing", "Generating score.")

                temp_path = mock_replace.call_args.args[0]
                self.assertFalse(os.path.exists(temp_path))

    def test_write_text_file_atomic_creates_readable_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = os.path.join(temp_dir, "nested", "score.html")

            score_models.write_text_file_atomic(html_path, "<html>cached</html>")

            with open(html_path, "r", encoding="utf-8") as html_file:
                self.assertEqual(html_file.read(), "<html>cached</html>")

    @patch("talkingscoresapp.models.os.replace", side_effect=OSError("replace failed"))
    def test_write_text_file_atomic_removes_temp_file_on_replace_failure(self, mock_replace):
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = os.path.join(temp_dir, "nested", "score.html")

            with self.assertRaises(OSError):
                score_models.write_text_file_atomic(html_path, "<html>cached</html>")

            temp_path = mock_replace.call_args.args[0]
            self.assertFalse(os.path.exists(temp_path))

    def test_html_can_raise_generation_errors_for_background_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score = TSScore(id=VALID_ID, filename="score.musicxml")
            data_path = os.path.join(temp_dir, VALID_ID, "score.musicxml")
            os.makedirs(os.path.dirname(data_path), exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as data_file:
                data_file.write("<score-partwise></score-partwise>")

            with patch.object(score, "get_data_file_path", return_value=data_path):
                with patch("talkingscoresapp.models.Music21TalkingScore", side_effect=ValueError("bad score")):
                    with patch.object(score.logger, "info"), patch.object(score.logger, "exception"):
                        with self.assertRaises(ValueError):
                            score.html(force_refresh=True, raise_errors=True)

                        self.assertIn("Error generating score", score.html(force_refresh=True))

    @patch("talkingscoresapp.models.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO)
    @patch("talkingscoresapp.models.Music21TalkingScore")
    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_streams_remote_file_with_timeout(self, mock_get, mock_music21, mock_dns):
        class FakeResponse:
            status_code = 200
            headers = {}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=65536):
                yield b"<score-partwise>"
                yield b"</score-partwise>"

        mock_get.return_value = FakeResponse()

        with tempfile.TemporaryDirectory() as temp_dir:
            destination_path = os.path.join(temp_dir, "score.musicxml")
            with patch.object(TSScore, "get_data_file_path", return_value=destination_path):
                score = TSScore.from_url("https://example.com/score.musicxml")

        # The request goes to the address that was checked, and still names the
        # host it was asked for, so the certificate is checked against that name.
        mock_get.assert_called_once_with(
            "https://93.184.216.34/score.musicxml",
            headers={"Host": "example.com"},
            timeout=score_models.REMOTE_FETCH_TIMEOUT,
            stream=True,
            allow_redirects=False,
            proxies=score_models.NO_PROXIES,
        )
        self.assertEqual(score.filename, "score.musicxml")
        mock_music21.assert_called()

    @patch("talkingscoresapp.models.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO)
    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_rejects_oversized_remote_file(self, mock_get, mock_dns):
        class FakeResponse:
            status_code = 200
            headers = {}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=65536):
                yield b"123456"

        mock_get.return_value = FakeResponse()

        with patch.object(score_models, "MAX_REMOTE_SCORE_BYTES", 5):
            with self.assertRaises(ValueError):
                TSScore.from_url("https://example.com/score.musicxml")

    @patch("talkingscoresapp.models.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO)
    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_gives_up_on_a_server_that_trickles(self, mock_get, mock_dns):
        class FakeResponse:
            status_code = 200
            headers = {}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=65536):
                while True:
                    yield b"x"

        mock_get.return_value = FakeResponse()

        with patch.object(score_models, "REMOTE_FETCH_DEADLINE_SECONDS", 0):
            with self.assertRaises(score_models.RemoteFetchRefused):
                TSScore.from_url("https://example.com/score.musicxml")

    @patch("talkingscoresapp.models.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO)
    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_refuses_a_declared_size_over_the_limit(self, mock_get, mock_dns):
        class FakeResponse:
            status_code = 200
            headers = {"Content-Length": str(11 * 1024 * 1024)}

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=65536):
                raise AssertionError("The body should not be read.")

        mock_get.return_value = FakeResponse()

        with self.assertRaises(score_models.RemoteFetchRefused):
            TSScore.from_url("https://example.com/score.musicxml")

    def test_info_refuses_a_score_that_was_never_uploaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(score_settings, "MEDIA_ROOT", temp_dir):
                with self.assertRaises(FileNotFoundError):
                    TSScore(id=VALID_ID, filename="score.musicxml").info()
            self.assertEqual(os.listdir(temp_dir), [])

    def test_from_url_rejects_unsupported_scheme(self):
        with self.assertRaises(ValueError):
            TSScore.from_url("file:///C:/temp/score.musicxml")

    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_rejects_hosts_on_private_networks(self, mock_get):
        private_addresses = [
            "127.0.0.1", "10.1.2.3", "192.168.0.5", "169.254.169.254", "::1", "::ffff:10.0.0.1", "0.0.0.0",
            "100.64.1.1", "64:ff9b::7f00:1", "64:ff9b:1::a00:1",
        ]
        for address in private_addresses:
            addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))]
            with patch("talkingscoresapp.models.socket.getaddrinfo", return_value=addrinfo):
                with self.assertRaises(score_models.RemoteAddressNotAllowed, msg=address):
                    TSScore.from_url("http://scores.example/score.musicxml")
        mock_get.assert_not_called()

    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_checks_every_redirect_hop(self, mock_get):
        class Redirect:
            status_code = 302
            headers = {"Location": "http://internal.example/score.musicxml"}

            def close(self):
                pass

        mock_get.return_value = Redirect()

        def resolve(host, *args, **kwargs):
            address = "10.0.0.9" if host == "internal.example" else "93.184.216.34"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 80))]

        with patch("talkingscoresapp.models.socket.getaddrinfo", side_effect=resolve):
            with self.assertRaises(score_models.RemoteAddressNotAllowed):
                TSScore.from_url("http://scores.example/score.musicxml")
        mock_get.assert_called_once()

    @patch("talkingscoresapp.models.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO)
    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_rejects_a_redirect_without_a_location(self, mock_get, mock_dns):
        class Redirect:
            status_code = 302
            headers = {}

            def close(self):
                pass

        mock_get.return_value = Redirect()

        with self.assertRaises(ValueError):
            TSScore.from_url("https://example.com/score.musicxml")
        self.assertIsNone(mock_get.call_args.kwargs["proxies"]["https"])

    @patch("talkingscoresapp.models.socket.getaddrinfo", side_effect=socket.gaierror)
    def test_homepage_explains_a_private_address_link(self, mock_dns):
        with patch("talkingscoresapp.views.TSScore.from_url", side_effect=score_models.RemoteAddressNotAllowed("private")):
            with patch.object(score_settings, "DEBUG", True):
                response = self.client.post(reverse("index"), {"url": "http://10.0.0.1/score.musicxml"}, follow=True)

        self.assertContains(response, "private or local network address")

    def test_mxl_extraction_refuses_a_manifest_with_entities(self):
        container = (
            '<?xml version="1.0"?><!DOCTYPE c [<!ENTITY a "aaaa">]>'
            '<container><rootfiles><rootfile full-path="real/score.xml"/></rootfiles></container>'
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            mxl_path = os.path.join(temp_dir, "score.mxl")
            with zipfile.ZipFile(mxl_path, "w") as archive:
                archive.writestr("META-INF/container.xml", container)
                archive.writestr("first.xml", "<fallback/>")
                archive.writestr("real/score.xml", "<score-partwise/>")
            output_path = os.path.join(temp_dir, "score.musicxml")

            with patch.object(score_models.logger, "info"):
                score_models.extract_musicxml_from_mxl(mxl_path, output_path)

            with open(output_path, encoding="utf-8") as output:
                self.assertEqual(output.read(), "<fallback/>")

    def test_mxl_extraction_caps_the_extracted_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mxl_path = os.path.join(temp_dir, "score.mxl")
            with zipfile.ZipFile(mxl_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("score.xml", "<a>" + "x" * 200 + "</a>")
            output_path = os.path.join(temp_dir, "score.musicxml")

            with patch.object(score_models, "MAX_EXTRACTED_SCORE_BYTES", 100):
                with patch.object(score_models.logger, "info"), patch.object(score_models.logger, "error"):
                    with self.assertRaises(Exception):
                        score_models.extract_musicxml_from_mxl(mxl_path, output_path)
            self.assertFalse(os.path.exists(output_path))

    def test_data_file_path_does_not_create_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score = TSScore(id=VALID_ID, filename="score.musicxml")
            score.get_data_file_path(root=temp_dir)
            self.assertEqual(os.listdir(temp_dir), [])

    def test_data_file_path_rejects_dot_only_filenames(self):
        with self.assertRaises(ValueError):
            TSScore(id=VALID_ID, filename="...").get_data_file_path(root="/tmp")

    def test_generated_html_escapes_the_title(self):
        from lib.talkingscoreslib import HTMLTalkingScoreFormatter
        template = HTMLTalkingScoreFormatter._setup_template_environment(Mock(), export_mode=False)

        html = template.render(reader_context(
            basic_information={"title": "<script>alert(1)</script>", "composer": "Composer"},
        ))

        self.assertNotIn("<script>alert(1)</script>", html)
    def test_mxl_extraction_follows_the_container_manifest(self):
        container = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container><rootfiles><rootfile full-path="real/score.xml" media-type="application/vnd.recordare.musicxml+xml"/></rootfiles></container>'
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            mxl_path = os.path.join(temp_dir, "score.mxl")
            with zipfile.ZipFile(mxl_path, "w") as archive:
                archive.writestr("aaa-first.xml", "<not-the-score/>")
                archive.writestr("META-INF/container.xml", container)
                archive.writestr("real/score.xml", "<score-partwise/>")
            output_path = os.path.join(temp_dir, "score.musicxml")

            with patch.object(score_models.logger, "info"):
                score_models.extract_musicxml_from_mxl(mxl_path, output_path)

            with open(output_path, encoding="utf-8") as output:
                self.assertEqual(output.read(), "<score-partwise/>")

    def test_cleanup_media_dry_run_and_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = os.path.join(temp_dir, "a" * 64)
            new_dir = os.path.join(temp_dir, "b" * 64)
            # Named as neither a score is, so the command has to leave it alone.
            other_dir = os.path.join(temp_dir, "music21")
            os.makedirs(old_dir)
            os.makedirs(new_dir)
            os.makedirs(other_dir)
            old_file = os.path.join(old_dir, "score.musicxml")
            new_file = os.path.join(new_dir, "score.musicxml")
            other_file = os.path.join(other_dir, "cache.p")
            with open(old_file, "w", encoding="utf-8") as file:
                file.write("old")
            with open(new_file, "w", encoding="utf-8") as file:
                file.write("new")
            with open(other_file, "w", encoding="utf-8") as file:
                file.write("cache")
            old_time = time.time() - (40 * 24 * 60 * 60)
            os.utime(old_file, (old_time, old_time))
            os.utime(other_file, (old_time, old_time))

            out = StringIO()
            with patch.object(cleanup_media, "MEDIA_ROOT", temp_dir):
                call_command("cleanup_media", "--older-than-days", "30", "--dry-run", stdout=out)
                self.assertTrue(os.path.isdir(old_dir))
                self.assertIn("Would remove", out.getvalue())

                call_command("cleanup_media", "--older-than-days", "30", stdout=StringIO())

            self.assertFalse(os.path.exists(old_dir))
            self.assertTrue(os.path.exists(new_dir))
            self.assertTrue(os.path.exists(other_file))


class GenerationLockTests(TestCase):
    """One generation run per score at a time, and a dead run never blocks the next one."""

    def _score_in(self, temp_dir):
        score = TSScore(id=VALID_ID, filename="score.musicxml")
        data_path = os.path.join(temp_dir, VALID_ID, "score.musicxml")
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        with open(data_path, "w", encoding="utf-8") as data_file:
            data_file.write("<score-partwise></score-partwise>")
        with open(data_path + ".opts", "w", encoding="utf-8") as opts_file:
            opts_file.write("{}")
        return score, data_path

    @staticmethod
    def _run_generate_inline(target, daemon):
        """Run the generate thread on the calling thread; the heartbeat stays a real thread."""
        if target.__name__ == "generate":
            return Mock(start=target)
        return REAL_THREAD(target=target, daemon=daemon)

    def _fake_formatter(self, html="<html>fresh</html>"):
        fake_formatter = Mock()
        fake_formatter.generateHTML.return_value = html
        fake_formatter.render_text.return_value = "text"
        fake_formatter.render_braille.return_value = "brf"
        return fake_formatter

    def test_lock_is_exclusive_while_a_run_is_live(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            other = TSScore(id=VALID_ID, filename="score.musicxml")
            with patch.object(score, "get_data_file_path", return_value=data_path), \
                    patch.object(other, "get_data_file_path", return_value=data_path):
                self.assertTrue(score.acquire_generation_lock())
                self.assertTrue(score.generation_is_live())

                self.assertFalse(other.acquire_generation_lock())
                with self.assertRaises(score_models.ScoreGenerationInProgress):
                    other.html(force_refresh=True)
                self.assertFalse(other.start_background_processing())

                score.release_generation_lock()
                self.assertTrue(other.acquire_generation_lock())
                other.release_generation_lock()

    def test_sync_generation_holds_the_lock_without_a_status_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            other = TSScore(id=VALID_ID, filename="score.musicxml")
            seen = {}

            def generate_and_probe(*args, **kwargs):
                seen["locked"] = other.acquire_generation_lock()
                return "<html>slow</html>"

            with patch.object(score, "get_data_file_path", return_value=data_path), \
                    patch.object(other, "get_data_file_path", return_value=data_path):
                with patch.object(score, "_generate_html", side_effect=generate_and_probe):
                    score.html(force_refresh=True)
            self.assertFalse(seen["locked"])
            self.assertFalse(os.path.exists(data_path + ".status"))

    def test_stale_lock_is_taken_over(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            other = TSScore(id=VALID_ID, filename="score.musicxml")
            with patch.object(score, "get_data_file_path", return_value=data_path), \
                    patch.object(other, "get_data_file_path", return_value=data_path):
                self.assertTrue(score.acquire_generation_lock())
                with patch("talkingscoresapp.models.time.time", return_value=time.time() + score_models.GENERATION_LOCK_STALE_SECONDS + 1):
                    self.assertFalse(score.generation_is_live())
                    with patch.object(score.logger, "warning"):
                        self.assertTrue(other.acquire_generation_lock())
                other.release_generation_lock()

    def test_refreshing_the_lock_keeps_it_live(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                self.assertTrue(score.acquire_generation_lock())
                stale_age = time.time() - score_models.GENERATION_LOCK_STALE_SECONDS - 1
                os.utime(data_path + ".lock", (stale_age, stale_age))
                self.assertFalse(score.generation_is_live())
                self.assertTrue(score.refresh_generation_lock())
                self.assertTrue(score.generation_is_live())
                score.release_generation_lock()

    def test_release_leaves_another_runs_lock_alone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            other = TSScore(id=VALID_ID, filename="score.musicxml")
            with patch.object(score, "get_data_file_path", return_value=data_path), \
                    patch.object(other, "get_data_file_path", return_value=data_path):
                self.assertTrue(score.acquire_generation_lock())
                other.release_generation_lock()
                self.assertTrue(os.path.exists(data_path + ".lock"))

                # A run whose lock was taken over must not refresh, report or release it.
                with patch("talkingscoresapp.models.time.time", return_value=time.time() + score_models.GENERATION_LOCK_STALE_SECONDS + 1):
                    with patch.object(other.logger, "warning"):
                        self.assertTrue(other.acquire_generation_lock())
                self.assertFalse(score.refresh_generation_lock())
                score.release_generation_lock()
                self.assertTrue(os.path.exists(data_path + ".lock"))
                other.release_generation_lock()
                self.assertFalse(os.path.exists(data_path + ".lock"))

    def test_status_and_cache_writes_are_skipped_after_options_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                epoch = score.options_epoch()
                with open(data_path + ".opts", "w", encoding="utf-8") as opts_file:
                    opts_file.write('{"bars_at_a_time": 8}')

                score._write_processing_status("complete", "Score ready.", epoch=epoch)
                self.assertFalse(os.path.exists(score.get_processing_status_file_path()))

                with patch("talkingscoresapp.models.Music21TalkingScore"), \
                        patch("talkingscoresapp.models.HTMLTalkingScoreFormatter", return_value=self._fake_formatter()), \
                        patch.object(score.logger, "info"):
                    score._generate_html(export_theme=None, export_mode=False, epoch=epoch)
                self.assertFalse(os.path.exists(score.get_html_cache_file_path()))

    def test_lock_is_released_after_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                with patch("talkingscoresapp.models.Music21TalkingScore"), \
                        patch("talkingscoresapp.models.HTMLTalkingScoreFormatter", return_value=self._fake_formatter()), \
                        patch.object(score.logger, "info"):
                    self.assertEqual(score.html(force_refresh=True), "<html>fresh</html>")
                self.assertFalse(os.path.exists(score.get_generation_lock_file_path()))
                self.assertTrue(os.path.exists(score.get_html_cache_file_path()))

    def test_background_run_reports_completion_and_releases_the_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                with patch("talkingscoresapp.models.Music21TalkingScore"), \
                        patch("talkingscoresapp.models.HTMLTalkingScoreFormatter", return_value=self._fake_formatter()), \
                        patch.object(score.logger, "info"), \
                        patch("talkingscoresapp.models.threading.Thread", side_effect=self._run_generate_inline):
                    self.assertTrue(score.start_background_processing())
                self.assertEqual(score.processing_status()["status"], "complete")
                self.assertFalse(os.path.exists(score.get_generation_lock_file_path()))

    def test_background_failure_stores_a_fixed_message(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                with patch("talkingscoresapp.models.Music21TalkingScore", side_effect=ValueError("secret path /srv/x")), \
                        patch.object(score.logger, "info"), patch.object(score.logger, "exception"), \
                        patch("talkingscoresapp.models.threading.Thread", side_effect=self._run_generate_inline):
                    self.assertTrue(score.start_background_processing())
                status = score.processing_status()
                self.assertEqual(status["status"], "failed")
                self.assertNotIn("secret", status["message"])
                self.assertFalse(os.path.exists(score.get_generation_lock_file_path()))

    def test_background_start_skips_a_fresh_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                score_models.write_text_file_atomic(data_path + ".html", "<html>cached</html>")
                with patch.object(score, "_generate_html") as mock_generate, \
                        patch("talkingscoresapp.models.threading.Thread", side_effect=self._run_generate_inline):
                    self.assertTrue(score.start_background_processing())
                mock_generate.assert_not_called()
                self.assertEqual(score.processing_status()["status"], "complete")
                self.assertFalse(os.path.exists(score.get_generation_lock_file_path()))

    def test_background_start_releases_the_lock_when_setup_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._score_in(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                with patch.object(score, "_write_processing_status", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        score.start_background_processing()
                self.assertFalse(os.path.exists(score.get_generation_lock_file_path()))

    @patch("talkingscoresapp.views.TSScore.state", return_value="processed")
    @patch("talkingscoresapp.views.TSScore.html", side_effect=score_models.ScoreGenerationInProgress("busy"))
    def test_score_page_waits_on_processing_page_while_locked(self, mock_html, mock_state):
        response = Client().get(reverse("score", kwargs={"id": VALID_ID, "filename": "score.musicxml"}))

        self.assertRedirects(response, reverse("process", kwargs={"id": VALID_ID, "filename": "score.musicxml"}), fetch_redirect_response=False)


class ReadingStyleTests(TestCase):
    """The description engine words the same facts differently for each reading style."""

    FIXTURE = os.path.join(os.getcwd(), "test_scores", "G1A1-flute-part.xml")
    GOLDEN_DIR = os.path.join(os.getcwd(), "talkingscoresapp", "golden")

    def _formatter(self, options):
        from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
        return HTMLTalkingScoreFormatter(Music21TalkingScore(self.FIXTURE), options=options)

    def test_each_style_matches_its_golden_text(self):
        from talkingscoreslib import HTMLTalkingScoreFormatter
        from lib.render_settings import STYLE_IDS
        for style in STYLE_IDS:
            with self.subTest(style=style):
                formatter = self._formatter({"style": style, "bars_at_a_time": 4})
                with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
                    text = formatter.render_text()
                with open(os.path.join(self.GOLDEN_DIR, f"{style}.txt"), encoding="utf-8") as golden:
                    self.assertEqual(text, golden.read())

    def test_the_set_up_page_samples_come_from_the_engine(self):
        from lib.render_settings import STYLE_IDS
        from lib.style_samples import style_samples
        samples = style_samples()
        for style in STYLE_IDS:
            with self.subTest(style=style):
                self.assertIn("D", samples[style])
        # Each style words the same bar differently, so no two samples read alike.
        self.assertEqual(len(set(samples.values())), len(STYLE_IDS))
        self.assertNotIn("Bar 1", samples["standard"])

    def test_page_uses_colour_classes_not_inline_styles(self):
        from talkingscoreslib import HTMLTalkingScoreFormatter
        formatter = self._formatter({
            "style": "standard", "colour_position": "words", "colour_pitch": True,
            "pitch_colours": {"C": "#ff0000", "D": "javascript:alert(1)"},
        })
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            html = formatter.generateHTML(web_path="/midis/x/y")
        self.assertIn('<body class="reader colour-words">', html)
        # The palette colour goes behind the word, with an ink that reads on it.
        self.assertIn(".colour-words .colour-pitch-c { background-color: #ff0000; color: black;", html)
        self.assertNotIn("javascript:", html)
        self.assertNotIn("style='color", html)
        self.assertIn('<span class="colour-pitch-c">C</span>', html)

    def test_braille_download_is_ascii_braille(self):
        from lib.braille import text_to_brf
        brf = text_to_brf("Bar 12\nSame as bar 3")
        self.assertEqual(brf.split("\r\n")[0], ",bar #ab")
        self.assertEqual(brf.split("\r\n")[1], ",same as bar #c")
        self.assertTrue(all(ord(char) < 128 for char in brf))

    def test_legacy_beat_division_sets_the_beat_unit(self):
        from lib.render_settings import RenderSettings
        settings = RenderSettings.from_options({"beat_division": "2/1.0", "rhythm_description": "american"})
        self.assertEqual(settings.beat_division, "beat")
        self.assertEqual(settings.beat_unit, 1.0)
        self.assertEqual(settings.duration_names, "american")
        self.assertEqual(RenderSettings.from_options({"beat_division": "bar"}).beat_division, "bar")

    def test_beats_are_numbered_from_the_offset(self):
        from lib.description import DescriptionBuilder
        self.assertEqual(DescriptionBuilder._beat_number(0.0, 1.0), 1)
        self.assertEqual(DescriptionBuilder._beat_number(1.75, 1.0), 2)
        self.assertEqual(DescriptionBuilder._beat_number(3.0, 1.5), 3)

    def test_plain_style_reads_lengths_in_beats(self):
        from lib.vocabulary import beats_phrase
        self.assertEqual(beats_phrase(1.0, 1.0), "1 beat")
        self.assertEqual(beats_phrase(0.5, 1.0), "half a beat")
        self.assertEqual(beats_phrase(3.0, 1.0), "3 beats")
        self.assertEqual(beats_phrase(1.5, 1.0), "1 and a half beats")

    def test_structural_rests_keep_only_rests_that_shape_the_bar(self):
        from lib.description import DescriptionBuilder
        from lib.events import TSRest
        from lib.render_settings import RenderSettings
        builder = DescriptionBuilder(RenderSettings.from_options({"style": "compact"}))
        short_rest = TSRest()
        short_rest.quarter_length = 0.5
        short_rest.start_offset = 1.5
        self.assertFalse(builder._rest_is_read(short_rest, 1.0, only_event_on_beat=False))
        self.assertTrue(builder._rest_is_read(short_rest, 1.0, only_event_on_beat=True))
        long_rest = TSRest()
        long_rest.quarter_length = 2.0
        long_rest.start_offset = 2.0
        self.assertTrue(builder._rest_is_read(long_rest, 1.0, only_event_on_beat=False))


class ReviewedEngineTests(TestCase):
    """Musical rules the description engine must keep: accidentals, graces, beats, percussion, colours, braille."""

    def _score_path(self, score_stream):
        temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)
        path = os.path.join(temp_dir, "score.musicxml")
        score_stream.write("musicxml", fp=path)
        return path

    @staticmethod
    def _score_of_bars(bars, time_signatures=None):
        """A one-part score; bars is a list of lists of music21 notes."""
        from music21 import stream, meter
        part = stream.Part()
        for index, items in enumerate(bars, start=1):
            measure = stream.Measure(number=index)
            signature = (time_signatures or {}).get(index, "4/4" if index == 1 else None)
            if signature:
                measure.append(meter.TimeSignature(signature))
            for item in items:
                measure.append(item)
            part.append(measure)
        score = stream.Score()
        score.append(part)
        return score

    def _text(self, score_stream, options):
        from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
        formatter = HTMLTalkingScoreFormatter(Music21TalkingScore(self._score_path(score_stream)), options=options)
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            return formatter.render_text()

    def test_a_named_style_keeps_its_wording_over_stored_form_choices(self):
        from lib.render_settings import RenderSettings
        stored = {
            "style": "plain", "rhythm_description": "british", "include_rests": True,
            "repetition_mode": "none", "octave_description": "name",
            "figureNoteColours": {"C": "#ff0000"}, "bars_at_a_time": 4,
        }
        plain = RenderSettings.from_options(stored)
        self.assertEqual(plain.duration_names, "plain")
        self.assertEqual(plain.rests, "structural")
        self.assertEqual(plain.repetition_mode, "learning")
        self.assertEqual(plain.octave_naming, "plain")
        self.assertEqual(plain.pitch_colours, {"C": "#ff0000"})
        self.assertEqual(plain.bars_at_a_time, 4)
        standard = RenderSettings.from_options({**stored, "style": "standard", "rhythm_description": "american"})
        self.assertEqual(standard.duration_names, "american")
        self.assertEqual(standard.repetition_mode, "none")

    @patch("talkingscoresapp.views.TSScore.info")
    @patch("talkingscoresapp.views.TSScore.get_data_file_path")
    @patch("talkingscoresapp.views.logger.info")
    def test_options_page_offers_every_reading_style(self, mock_logger_info, mock_data_path, mock_info):
        mock_data_path.return_value = "/tmp/score.musicxml"
        mock_info.return_value = {"title": "Score", "composer": "Composer", "instruments": ["Piano"],
                                  "rhythm_range": [], "beat_division_options": []}
        response = self.client.get(reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"}))
        self.assertContains(response, 'name="style"')
        for name in ("Everyday words", "Musical terms", "Short", "Braille display", "Everything"):
            self.assertContains(response, f">{name}<")

    @patch("talkingscoresapp.views.TSScore.info")
    @patch("talkingscoresapp.views.TSScore.get_data_file_path")
    @patch("talkingscoresapp.views.logger.info")
    def test_options_page_keeps_the_detail_behind_one_disclosure(self, mock_logger_info, mock_data_path, mock_info):
        mock_data_path.return_value = "/tmp/score.musicxml"
        mock_info.return_value = {"title": "Score", "composer": "Composer", "instruments": ["Piano"],
                                  "rhythm_range": [], "beat_division_options": []}
        response = self.client.get(reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"}))
        content = response.content.decode("utf-8")

        # The style choice is the page; every other setting is folded away behind it.
        first_disclosure = content.index("<details")
        self.assertLess(content.index('name="style"'), first_disclosure)
        self.assertIn("Generate the reading", content)

        form = content[content.index('<form class="form"'):]
        outside = re.findall(r'name="([^"]+)"', form[:form.index("<details")])
        self.assertEqual(sorted(set(outside)), ["csrfmiddlewaretoken", "style"])

    def test_unpitched_parts_are_described_instead_of_failing(self):
        from music21 import note
        drums = self._score_of_bars([[note.Unpitched(quarterLength=1.0) for _ in range(4)]])
        text = self._text(drums, {"style": "standard"})
        self.assertIn("Beat 1 crotchet unpitched", text)
        self.assertNotIn("Rests for the whole bar", text)

    def test_colour_map_keys_never_reach_the_stylesheet_unchecked(self):
        from lib.description import clean_colour_map
        from talkingscoreslib import PITCH_COLOUR_KEYS, Music21TalkingScore, HTMLTalkingScoreFormatter
        cleaned = clean_colour_map({"C</style><script>alert(1)</script>": "#ff0000", "D": "#00ff00", "x": "#0000ff"}, PITCH_COLOUR_KEYS)
        self.assertEqual(cleaned, {"d": "#00ff00"})
        formatter = HTMLTalkingScoreFormatter(
            Music21TalkingScore(os.path.join(os.getcwd(), "test_scores", "G1A1-flute-part.xml")),
            options={"style": "standard", "colour_position": "words", "colour_pitch": True,
                     "octave_colour_mode": "custom",
                     "pitch_colours": {"C</style><script>alert(1)</script>": "#ff0000"},
                     "octave_colours": {"high{}body{display:none}": "#ff0000"}})
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            html = formatter.generateHTML(web_path="/midis/x/y")
        self.assertNotIn("<script>alert(1)", html)
        self.assertNotIn("body{display:none}", html)

    def test_accidentals_are_forgotten_at_the_bar_line(self):
        from music21 import note
        score = self._score_of_bars([
            [note.Note("F#4"), note.Note("F#4"), note.Note("G4"), note.Note("A4")],
            [note.Note("F#4"), note.Note("F4"), note.Note("G4"), note.Note("A4")],
        ])
        text = self._text(score, {"style": "standard", "key_signature_accidentals": "on_change", "bars_at_a_time": 2})
        bar_two = text.split("Bar 2")[1]
        self.assertIn("F sharp", bar_two)

    def test_a_note_is_named_by_the_pitch_it_sounds(self):
        from music21 import note, key
        first, cancelled = note.Note("F#4"), note.Note("F4")
        cancelled.pitch.accidental = "natural"
        # D major, so the key sharpens F. The third note is written as a bare F:
        # the natural before it still applies, so it sounds F natural too.
        score = self._score_of_bars([[key.KeySignature(2), first, cancelled, note.Note("F4"), note.Note("F#4")]])
        text = self._text(score, {"style": "standard"})
        beats = [line for line in text.splitlines() if line.startswith("Beat")][0]
        self.assertEqual(beats, "Beat 1 crotchet mid F sharp, Beat 2 F, Beat 3 F, Beat 4 F sharp")
        # Nothing is read as natural: a letter on its own is the note it names.
        self.assertNotIn("natural", text)

    def test_an_unusual_spelling_is_read_as_the_plainer_note(self):
        from music21 import note
        score = self._score_of_bars([[note.Note("C-4"), note.Note("E#4"), note.Note("F##4"), note.Note("G#4")]])
        beats = [line for line in self._text(score, {"style": "standard"}).splitlines()
                 if line.startswith("Beat")][0]
        # C flat sounds a B, and an octave lower than the letter suggests.
        self.assertEqual(beats, "Beat 1 crotchet low B, Beat 2 mid F, Beat 3 G, Beat 4 G sharp")

    def test_the_printed_mode_reads_every_accidental_the_music_prints(self):
        from music21 import note
        sharp, natural = note.Note("F#4"), note.Note("F4")
        natural.pitch.accidental = "natural"
        score = self._score_of_bars([[sharp, natural, note.Note("G4"), note.Note("A4")]])
        text = self._text(score, {"style": "standard", "key_signature_accidentals": "printed"})
        # The natural cancels the sharp earlier in the bar, and the page prints it.
        self.assertIn("F sharp", text)
        self.assertIn("F natural", text)

    def test_an_older_options_file_still_names_an_accidental_mode(self):
        from lib.render_settings import RenderSettings
        self.assertEqual(RenderSettings.from_options(
            {"key_signature_accidentals": "applied"}).key_signature_accidentals, "sounding")
        self.assertEqual(RenderSettings.from_options(
            {"key_signature_accidentals": "standard"}).key_signature_accidentals, "printed")

    def test_a_tuplet_is_read_when_the_file_leaves_the_bracket_out(self):
        from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
        # The fixture carries the time modification on each note and no bracket,
        # which is all a file has to write.
        formatter = HTMLTalkingScoreFormatter(
            Music21TalkingScore(os.path.join(os.getcwd(), "test_scores", "triplet-without-brackets.musicxml")),
            options={"style": "standard"})
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            text = formatter.render_text()
        self.assertIn("triplets quaver", text)
        self.assertEqual(text.count("end tuplet"), 1)

    def test_two_bracketed_tuplets_in_a_bar_stay_two_groups(self):
        from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
        # The fixture brackets a triplet crotchet plus quaver, then three triplet
        # quavers. Working the groups out from the notes would run them together.
        formatter = HTMLTalkingScoreFormatter(
            Music21TalkingScore(os.path.join(os.getcwd(), "test_scores", "two-triplet-groups.musicxml")),
            options={"style": "standard"})
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            text = formatter.render_text()
        self.assertEqual(text.count("triplets"), 2)
        self.assertEqual(text.count("end tuplet"), 2)

    def test_a_bar_a_hairpin_runs_through_is_not_collapsed_into_the_one_before(self):
        from music21 import dynamics, note
        bars = [[note.Note("C4") for _ in range(4)] for _ in range(3)]
        score = self._score_of_bars(bars)
        part = score.parts[0]
        measures = list(part.getElementsByClass("Measure"))
        part.insert(0, dynamics.Crescendo(measures[1].notes[0], measures[1].notes[-1]))
        text = self._text(score, {"style": "standard", "repetition_mode": "learning", "bars_at_a_time": 3})
        # The crescendo is the only thing telling bar 2 from bar 1, and it is held
        # by the part rather than written inside the bar.
        self.assertIn("crescendo", text)
        self.assertNotIn("Bar 2\nSame as bar 1", text)

    def test_a_bar_spelt_differently_is_not_collapsed_into_the_one_before(self):
        from music21 import note
        sharps = [note.Note("F#4") for _ in range(4)]
        flats = [note.Note("G-4") for _ in range(4)]
        score = self._score_of_bars([sharps, flats])
        text = self._text(score, {"style": "standard", "repetition_mode": "learning", "bars_at_a_time": 2})
        self.assertNotIn("Same as bar", text)
        self.assertIn("G flat", text)
        repeated = self._score_of_bars([sharps, [note.Note("F#4") for _ in range(4)]])
        self.assertIn("Same as bar 1", self._text(repeated, {"style": "standard", "repetition_mode": "learning", "bars_at_a_time": 2}))

    def test_the_tied_notes_of_a_chord_are_named_after_the_chord(self):
        from music21 import chord, note, tie
        held = chord.Chord(["C4", "E4", "G4"])
        held.notes[0].tie = tie.Tie("start")
        two = chord.Chord(["C4", "E4", "G4"])
        two.notes[0].tie = tie.Tie("start")
        two.notes[2].tie = tie.Tie("start")
        whole = chord.Chord(["C4", "E4", "G4"])
        whole.tie = tie.Tie("start")
        score = self._score_of_bars([
            [held, note.Rest(quarterLength=3)],
            [two, note.Rest(quarterLength=3)],
            [whole, note.Rest(quarterLength=3)],
        ])
        text = self._text(score, {"style": "standard", "bars_at_a_time": 3, "repetition_mode": "none"})
        one, two_text, three = text.split("\nBar ")[1:4]
        # The chord is heard whole first, then the notes that are held, named
        # again with their octaves so the tie cannot attach to the wrong one.
        self.assertIn("mid C E G with mid C tied to next", one)
        self.assertIn("mid C E G with mid C and mid G tied to next", two_text)
        # A tie over the whole chord is still read once for the chord.
        self.assertIn("mid C E G tied to next", three)
        self.assertNotIn("with", three)

    def test_a_hairpin_ends_after_the_note_it_closes_on(self):
        from music21 import dynamics, note
        notes = [note.Note("C4"), note.Note("D4"), note.Note("E4"), note.Note("F4")]
        score = self._score_of_bars([notes])
        score.parts[0].insert(0, dynamics.Crescendo(notes[0], notes[2]))
        text = self._text(score, {"style": "standard"})
        self.assertIn("crescendo starts, crotchet mid C", text)
        self.assertIn("E, crescendo ends", text)

    def test_a_gap_in_the_bar_numbers_does_not_end_the_reading(self):
        from music21 import note, stream, meter
        part = stream.Part()
        for number in (1, 2, 7, 8):
            measure = stream.Measure(number=number)
            if number == 1:
                measure.append(meter.TimeSignature("4/4"))
            for _ in range(4):
                measure.append(note.Note("C4"))
            part.append(measure)
        score = stream.Score()
        score.append(part)
        text = self._text(score, {"style": "standard", "bars_at_a_time": 2})
        self.assertIn("Bar 7", text)
        self.assertIn("Bar 8", text)

    def test_drums_struck_together_are_read_and_do_not_stop_the_reading(self):
        from music21 import note, percussion
        struck = percussion.PercussionChord([note.Unpitched(), note.Unpitched()])
        struck.quarterLength = 1.0
        score = self._score_of_bars([[struck, note.Unpitched(quarterLength=3)]])
        text = self._text(score, {"style": "standard"})
        # The file names no drum for either line, so the count is what is left to read.
        self.assertIn("crotchet 2 unpitched together", text)
        self.assertIn("dotted minim unpitched", text)

    def test_a_drum_is_read_by_name_where_the_file_names_it(self):
        from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
        formatter = HTMLTalkingScoreFormatter(
            Music21TalkingScore(os.path.join(os.getcwd(), "test_scores", "drum-kit.musicxml")),
            options={"style": "standard"})
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            text = formatter.render_text()
        self.assertIn("crotchet Acoustic Snare and Closed Hi-Hat", text)
        self.assertIn("crotchet Closed Hi-Hat", text)
        self.assertNotIn("unpitched", text)

    def test_both_halves_of_a_repeat_ending_are_read_and_addressable(self):
        from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
        score = Music21TalkingScore(os.path.join(os.getcwd(), "test_scores", "G1A1-flute-part.xml"))
        formatter = HTMLTalkingScoreFormatter(score, options={"style": "standard", "bars_at_a_time": 4})
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            text = formatter.render_text()
        # The file prints 13 on both halves of a first- and second-time ending; each
        # is counted as a bar of its own so the second is read rather than dropped.
        self.assertIn("Bar 13\nBeat 1 minim high F", text)
        self.assertIn("Bar 13, second time\n", text)
        self.assertIn("Beat 1 minim high G, Beat 3 crotchet mid B", text)
        self.assertEqual(score.bar_label(13), "13")
        self.assertEqual(score.bar_label(14), "13, second time")
        # The counted number reaches one bar and only one, so the second-time bar
        # can be played on its own.
        events = score.get_events_for_bar_range(14, 14, 0)
        self.assertEqual(sorted(events.keys()), [14])
        self.assertTrue(events[14])

    def test_slurs_and_articulations_are_read_with_the_notes_they_mark(self):
        from music21 import articulations, note, spanner
        notes = [note.Note("C4"), note.Note("D4"), note.Note("E4"), note.Note("F4")]
        notes[0].articulations.append(articulations.Staccato())
        notes[1].articulations.append(articulations.Accent())
        score = self._score_of_bars([notes])
        score.parts[0].insert(0, spanner.Slur(notes[0], notes[2]))
        text = self._text(score, {"style": "standard"})
        self.assertIn("mid C staccato slur starts", text)
        self.assertIn("D accent", text)
        self.assertIn("E slur ends", text)
        without = self._text(score, {"style": "standard", "slurs": False, "articulations": False})
        self.assertNotIn("slur", without)
        self.assertNotIn("staccato", without)

    def test_repeats_endings_clefs_and_directions_are_read_where_they_are_written(self):
        from music21 import bar, clef, expressions, note, repeat, spanner, stream, meter
        first = stream.Measure(number=1)
        first.append(meter.TimeSignature("4/4"))
        for pitch in ("C4", "D4", "E4", "F4"):
            first.append(note.Note(pitch))
        first.leftBarline = bar.Repeat(direction="start")
        first.rightBarline = bar.Repeat(direction="end", times=3)
        first.insert(0, expressions.TextExpression("dolce"))
        second = stream.Measure(number=2)
        second.append(clef.BassClef())
        for pitch in ("G3", "A3", "B3", "C4"):
            second.append(note.Note(pitch))
        second.insert(0, repeat.Segno())
        second.insert(0, repeat.DaCapoAlFine())
        part = stream.Part()
        part.append(first)
        part.append(second)
        bracket = spanner.RepeatBracket(number=1)
        bracket.addSpannedElements(first)
        part.insert(0, bracket)
        score = stream.Score()
        score.append(part)
        text = self._text(score, {"style": "standard", "bars_at_a_time": 2})
        for line in ("Repeat starts", "1st time", "dolce", "Repeat ends, play 3 times",
                     "Bass clef", "Segno", "Da Capo al fine"):
            self.assertIn(line, text)
        self.assertLess(text.index("Repeat starts"), text.index("Beat 1"))
        self.assertLess(text.index("Beat 1"), text.index("Repeat ends"))
        self.assertNotIn("dolce", self._text(score, {"style": "standard", "directions": False, "bars_at_a_time": 2}))

    def test_the_movement_name_is_the_title_when_the_file_gives_no_other(self):
        from music21 import note
        from talkingscoreslib import Music21TalkingScore
        score = self._score_of_bars([[note.Note("C4")]])
        path = self._score_path(score)
        # music21 writes its own name and the file's name into a file it saves.
        self.assertEqual(Music21TalkingScore(path).get_title(), "Untitled work")
        self.assertEqual(Music21TalkingScore(path).get_composer(), "Unknown composer")
        named = Music21TalkingScore(path)
        named.score.metadata.movementName = "Second movement"
        self.assertEqual(named.get_title(), "Second movement")

    def test_a_pickup_bar_is_not_counted_as_a_bar(self):
        from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
        fixture = os.path.join(os.getcwd(), "test_scores", "Paganini - Le Streghe mvt 2.xml")
        formatter = HTMLTalkingScoreFormatter(Music21TalkingScore(fixture), options={"style": "standard"})
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            formatter.build()
        self.assertEqual(formatter.segments[0].label, "Pickup bar")
        # The page counts the bars the same way the player does.
        self.assertEqual(formatter._get_preamble()["number_of_bars"],
                         formatter._score_data("", False)["totalBars"])

    def test_grace_notes_are_read_before_the_note_they_decorate(self):
        from music21 import note
        grace = note.Note("D5").getGrace()
        score = self._score_of_bars([[grace, note.Note("C5"), note.Note("B4"), note.Note("A4"), note.Note("G4")]])
        text = self._text(score, {"style": "standard"})
        self.assertIn("grace note", text)
        self.assertNotIn("together with", text)
        self.assertLess(text.index("grace note"), text.index("crotchet"))

    def test_beats_follow_a_time_signature_change_inside_a_segment(self):
        from music21 import note
        score = self._score_of_bars(
            [[note.Note("C4") for _ in range(4)], [note.Note("D4", quarterLength=0.5) for _ in range(6)]],
            time_signatures={1: "4/4", 2: "6/8"})
        text = self._text(score, {"style": "standard", "bars_at_a_time": 2})
        bar_two = text.split("Bar 2")[1]
        self.assertIn("Beat 2", bar_two)
        self.assertNotIn("Beat 3", bar_two)

    def test_folded_repeats_are_folded_in_the_text_download_too(self):
        from lib.description import BarDescription, BeatDescription, Fragment
        bar = BarDescription(number=2, label="Bar 2", repeat_note="Same as bar 1", collapsed=True,
                             beats=[BeatDescription(1, "Beat 1", [Fragment("crotchet C")])])
        self.assertEqual(bar.text_lines(), ["Bar 2", "Same as bar 1"])
        bar.collapsed = False
        self.assertEqual(bar.text_lines(), ["Bar 2", "Same as bar 1", "Beat 1 crotchet C"])

    def test_tempo_is_stated_only_when_the_file_gives_one(self):
        from music21 import note, tempo
        from talkingscoreslib import Music21TalkingScore
        from lib.render_settings import RenderSettings
        silent = self._score_of_bars([[note.Note("C4") for _ in range(4)]])
        self.assertEqual(Music21TalkingScore(self._score_path(silent)).get_initial_tempo(), "")
        marked = self._score_of_bars([[tempo.MetronomeMark(number=96)] + [note.Note("C4") for _ in range(4)]])
        score = Music21TalkingScore(self._score_path(marked), settings=RenderSettings.for_style("plain"))
        self.assertEqual(score.get_initial_tempo(), "96 crotchet beats a minute")

    def test_braille_octave_marks_count_letter_steps(self):
        from lib.description import DescriptionBuilder
        from lib.events import TSPitch
        from lib.render_settings import RenderSettings
        builder = DescriptionBuilder(RenderSettings.for_style("braille40"))
        c4 = TSPitch("C", 4, 0, 60)
        self.assertFalse(builder._octave_is_read(TSPitch("A", 4, 0, 69), c4))   # a sixth, same octave
        self.assertFalse(builder._octave_is_read(TSPitch("C", 5, 0, 72), TSPitch("G", 4, 0, 67)))  # a fourth
        self.assertTrue(builder._octave_is_read(TSPitch("D", 5, 0, 74), c4))    # a ninth

    def test_braille_keeps_the_letters_of_accented_names(self):
        from lib.braille import text_to_brf
        self.assertTrue(text_to_brf("Fauré").startswith(",faure"))
        self.assertIn("=", text_to_brf("Ø"))

    def test_contrast_colour_reads_short_hex(self):
        from lib.description import contrast_colour
        self.assertEqual(contrast_colour("#ff0"), "black")
        self.assertEqual(contrast_colour("#000"), "white")

    def test_the_tuplet_close_follows_the_last_note(self):
        from lib.description import DescriptionBuilder, PartState
        from lib.events import TSNote, TSPitch
        from lib.render_settings import RenderSettings
        builder = DescriptionBuilder(RenderSettings.for_style("standard"))
        last = TSNote()
        last.pitch = TSPitch("C", 4, 0, 60)
        last.duration_type, last.quarter_length, last.tuplet_stop = "eighth", 1 / 3, True
        text = "".join(fragment.text for fragment in builder.render_event(last, PartState()))
        self.assertEqual(text, "quaver mid C end tuplet")

    def test_a_single_bar_segment_names_the_bar_once(self):
        from lib.description import segments_to_text, SegmentDescription, InstrumentDescription, PartDescription, BarDescription
        bar = BarDescription(number=1, label="Bar 1", whole_bar_rest=True, rest_text="Rests for the whole bar")
        part = PartDescription(part_index=0, name="Flute", bars=[bar])
        segment = SegmentDescription(start_bar=1, end_bar=1, label="Bar 1", anchor="segment-1", is_pickup=False,
                                     instruments=[InstrumentDescription(number=1, name="Flute", parts=[part])])
        self.assertEqual(segments_to_text([segment]), "Bar 1\nRests for the whole bar\n")

    def test_a_missing_export_is_reported_not_opened(self):
        score = TSScore(id=VALID_ID, filename="score.musicxml")
        with patch.object(score, "get_text_cache_file_path", return_value=None), \
                patch.object(score, "get_data_file_path", return_value=None), \
                patch.object(score, "html"):
            with self.assertRaises(FileNotFoundError):
                score.export_text()


class ReaderPageTests(TestCase):
    """The score page is built bar by bar, and the downloaded copy stands on its own."""

    FIXTURE = os.path.join(os.getcwd(), "test_scores", "G1A1-flute-part.xml")

    def _formatter(self, options):
        from talkingscoreslib import Music21TalkingScore, HTMLTalkingScoreFormatter
        return HTMLTalkingScoreFormatter(Music21TalkingScore(self.FIXTURE), options=options)

    def _render(self, formatter, **kwargs):
        from talkingscoreslib import HTMLTalkingScoreFormatter
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            return formatter.generateHTML(**kwargs)

    def test_a_segment_is_read_bar_by_bar_with_parts_inside_each_bar(self):
        from lib.description import (SegmentDescription, InstrumentDescription, PartDescription,
                                     BarDescription)
        flute = PartDescription(0, "Flute", bars=[BarDescription(3, "Bar 3"), BarDescription(4, "Bar 4")])
        oboe = PartDescription(1, "Oboe", bars=[BarDescription(3, "Bar 3"), BarDescription(4, "Bar 4")])
        segment = SegmentDescription(3, 4, "Bars 3 to 4", "segment-3", instruments=[
            InstrumentDescription(1, "Flute", parts=[flute]), InstrumentDescription(2, "Oboe", parts=[oboe])])
        bars = segment.bars
        self.assertEqual([bar["number"] for bar in bars], [3, 4])
        self.assertEqual([bar["label"] for bar in bars], ["Bar 3", "Bar 4"])
        self.assertEqual([part["label"] for part in bars[0]["parts"]], ["Flute", "Oboe"])
        self.assertIs(bars[1]["parts"][1]["bar"], oboe.bars[1])

        gap = SegmentDescription(3, 5, "Bars 3 to 5", "segment-3", instruments=[
            InstrumentDescription(1, "Flute", parts=[flute])])
        self.assertEqual([(bar["number"], len(bar["parts"])) for bar in gap.bars], [(3, 1), (4, 1), (5, 0)])

        solo = SegmentDescription(3, 4, "Bars 3 to 4", "segment-3",
                                  instruments=[InstrumentDescription(1, "Flute", parts=[flute])])
        self.assertEqual([part["label"] for part in solo.bars[0]["parts"]], [""])

    def test_the_page_carries_what_the_reader_script_needs(self):
        html = self._render(self._formatter({"style": "standard", "bars_at_a_time": 3}),
                            web_path="/midis/x/y.musicxml", options_url="/score_options/x/y.musicxml")
        data = json.loads(re.search(r'id="score-data">(.*?)</script>', html, re.S).group(1))
        # The fixture prints 24 bar numbers; the last is printed twice, for a first-
        # and second-time ending, and both halves are read.
        self.assertEqual((data["firstBar"], data["firstNumberedBar"], data["lastBar"], data["totalBars"]),
                         (1, 1, 25, 25))
        self.assertIsNone(data["pickupBar"])
        self.assertEqual(data["barsPerGroup"], 3)
        self.assertEqual(data["groupSizes"], [1, 2, 3, 4, 8])
        self.assertEqual(data["midi"]["base"], "/midis/x/y.musicxml")
        self.assertEqual(data["midi"]["parts"], [{"index": 0, "label": "Instrument 1 (unnamed)", "read": True}])
        self.assertEqual(data["midi"]["voices"], [{"parts": [0], "label": "Instrument 1 (unnamed)"}])
        self.assertIn('<div class="bar" id="bar-1" data-bar="1"', html)
        self.assertIn("<small>Bar</small> 1</h3>", html)
        self.assertNotIn("group-toggle", html)           # the script builds the group buttons
        self.assertIn('href="/score_options/x/y.musicxml"', html)
        self.assertIn('src="/static/js/player.js" defer', html)
        self.assertIn("Metronome click", html)
        self.assertIn('id="setting-repeat"', html)
        self.assertIn('id="download-midi"', html)
        self.assertNotIn('id="setting-voice"', html)     # one voice needs no choice
        self.assertNotIn('id="setting-forward"', html)   # one part cannot be brought forward
        self.assertNotIn("midijs.net", html)             # the page sounds the MIDI itself

    def test_the_page_offers_a_way_to_play_each_group_of_instruments(self):
        formatter = self._formatter({"style": "standard", "play_all": True, "play_selected": True,
                                     "play_unselected": True})
        with patch.object(type(formatter), "_trigger_midi_generation"):
            formatter.build("", "/midis/x/y.musicxml")
        formatter.score.part_instruments = {
            1: ["Flute", 0, 1, "P1"], 2: ["Oboe", 1, 1, "P2"], 3: ["Cello", 2, 1, "P3"]}
        formatter.score.selected_instruments = [1, 2]
        formatter.score.unselected_instruments = [3]
        formatter.settings.play_all = True
        formatter.settings.play_selected = True
        formatter.settings.play_unselected = True
        parts = formatter._playback_parts()
        self.assertEqual([(part["index"], part["label"], part["read"]) for part in parts],
                         [(0, "Flute", True), (1, "Oboe", True), (2, "Cello", False)])
        voices = formatter._playback_voices(parts)
        self.assertEqual([voice["label"] for voice in voices][:3],
                         ["Every instrument", "The instruments being read", "The other instruments"])
        self.assertEqual(voices[0]["parts"], [0, 1, 2])
        self.assertEqual(voices[1]["parts"], [0, 1])
        self.assertEqual(voices[2]["parts"], [2])
        self.assertIn(["Flute", [0]], [[voice["label"], voice["parts"]] for voice in voices])

    def test_the_meta_line_names_only_the_instruments_being_read(self):
        formatter = self._formatter({"style": "standard"})
        with patch.object(type(formatter), "_trigger_midi_generation"):
            formatter.build("", "/midis/x/y.musicxml")
        formatter.score.part_instruments = {
            1: ["Flute", 0, 1, "P1"], 2: ["Flute", 1, 1, "P2"], 3: ["Flute", 2, 1, "P3"],
            4: ["Oboe", 3, 1, "P4"], 5: ["Horn", 4, 1, "P5"], 6: ["Cello", 5, 1, "P6"], 7: ["Bass", 6, 1, "P7"],
        }
        formatter.score.selected_instruments = [1, 2, 3, 4, 5, 6, 7]
        line = formatter._meta_line()
        self.assertEqual(line[-6:], ["Flute", "Oboe", "Horn", "Cello", "and 1 more", "25 bars"])
        formatter.score.selected_instruments = [4]
        self.assertEqual(formatter._meta_line()[-2:], ["Oboe", "25 bars"])

    def test_the_page_labels_a_repeat_ending_by_its_printed_number(self):
        html = self._render(self._formatter({"style": "standard", "bars_at_a_time": 4}))
        data = json.loads(re.search(r'id="score-data">(.*?)</script>', html, re.S).group(1))
        # The go-to box takes the number printed on the page, which stops one short of
        # the bar count when a repeat ending prints its number twice.
        self.assertEqual((data["firstPrintedBar"], data["lastPrintedBar"]), (1, 24))
        self.assertIn('data-bar="14" data-printed="13, second time"', html)
        self.assertIn("<small>Bar</small> 13, second time</h3>", html)

    def test_a_pickup_bar_keeps_go_to_bar_on_numbered_bars(self):
        from talkingscoreslib import HTMLTalkingScoreFormatter
        formatter = self._formatter({"style": "standard", "bars_at_a_time": 2})
        with patch.object(HTMLTalkingScoreFormatter, "_trigger_midi_generation"):
            formatter.build("", "/midis/x/y.musicxml")
        formatter.segments[0].is_pickup = True
        formatter.segments[0].end_bar = formatter.segments[0].start_bar
        data = formatter._score_data("/midis/x/y.musicxml", export_mode=False)
        self.assertEqual(data["pickupBar"], data["firstBar"])
        self.assertEqual(data["firstNumberedBar"], data["firstBar"] + 1)
        self.assertEqual(data["totalBars"], data["lastBar"] - data["firstNumberedBar"] + 1)

        # A score that is nothing but a pickup bar cannot ask for a bar after it.
        formatter.segments = formatter.segments[:1]
        data = formatter._score_data("/midis/x/y.musicxml", export_mode=False)
        self.assertEqual(data["firstNumberedBar"], data["firstBar"])
        self.assertEqual(data["lastBar"], data["firstBar"])

    def test_a_score_with_no_bars_says_so(self):
        env = Environment(loader=FileSystemLoader(os.path.join(os.getcwd(), "lib")), autoescape=True)
        html = env.get_template("talkingscore.html").render(reader_context())
        self.assertIn("No bars could be read from this file.", html)
        self.assertNotIn('id="toolbar"', html)
        self.assertEqual(html.count('id="score"'), 1)

    def test_the_downloaded_page_needs_no_server(self):
        html = self._render(self._formatter({"style": "standard"}), web_path="/midis/x/y.musicxml",
                            download_html_url="/download/html/x/y", options_url="/score_options/x/y",
                            export_mode=True, export_theme="dark")
        self.assertIn('<html lang="en-GB" data-theme="dark">', html)
        self.assertNotIn("<link ", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("/download/", html)
        self.assertNotIn("/score_options/", html)
        self.assertIn('"midi": null', html)
        self.assertIn("talkingscores.reader", html)      # the reader script is inlined
        self.assertIn("--note: 28px", html)              # so is the stylesheet

class ExportDownloadTests(TestCase):
    """The text and braille downloads serve the cached exports as attachments."""

    def test_text_download_serves_the_cached_text(self):
        with patch.object(TSScore, "state", return_value=score_models.TSScoreState.PROCESSED), \
                patch.object(TSScore, "export_text", return_value="Bar 1\nBeat 1 crotchet C\n") as export:
            response = self.client.get(f"/download/text/{VALID_ID}/score.musicxml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn('filename="score-talking-score.txt"', response["Content-Disposition"])
        self.assertEqual(response.content.decode("utf-8"), "Bar 1\nBeat 1 crotchet C\n")
        export.assert_called_once_with(braille=False)

    def test_braille_download_serves_the_cached_brf(self):
        with patch.object(TSScore, "state", return_value=score_models.TSScoreState.PROCESSED), \
                patch.object(TSScore, "export_text", return_value=",bar #a\r\n") as export:
            response = self.client.get(f"/download/braille/{VALID_ID}/score.musicxml")
        self.assertEqual(response.status_code, 200)
        self.assertIn('filename="score-talking-score.brf"', response["Content-Disposition"])
        self.assertEqual(response.content, b",bar #a\r\n")
        export.assert_called_once_with(braille=True)

    def test_downloads_redirect_home_when_the_score_is_not_ready(self):
        with patch.object(TSScore, "state", return_value=score_models.TSScoreState.FETCHING):
            response = self.client.get(f"/download/text/{VALID_ID}/score.musicxml")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_generating_the_page_writes_the_text_and_braille_caches(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = os.path.join(temp_dir, "score.musicxml")
            with open(data_path, "w", encoding="utf-8") as data_file:
                data_file.write("<score-partwise></score-partwise>")
            with open(data_path + ".opts", "w", encoding="utf-8") as opts_file:
                opts_file.write("{}")
            score = TSScore(id=VALID_ID, filename="score.musicxml")
            fake = Mock()
            fake.generateHTML.return_value = "<html>page</html>"
            fake.render_text.return_value = "Bar 1\n"
            fake.render_braille.return_value = ",bar #a\r\n"
            with patch.object(score, "get_data_file_path", return_value=data_path), \
                    patch.object(score_models, "Music21TalkingScore"), \
                    patch.object(score_models, "HTMLTalkingScoreFormatter", return_value=fake):
                score.html(force_refresh=True, raise_errors=True)
                self.assertEqual(score.export_text(), "Bar 1\n")
                self.assertEqual(score.export_text(braille=True), ",bar #a\r\n")
            fake.generateHTML.assert_called_once()


class ReviewFixTests(TestCase):
    """Edge cases raised in review: bad colours, unknown hosts, unusable names, dead-end pages and lock races."""

    @patch("talkingscoresapp.views.TSScore.info")
    @patch("talkingscoresapp.views.TSScore.get_data_file_path")
    @patch("talkingscoresapp.views.TSScore.clear_generated_html_state")
    @patch("talkingscoresapp.views.logger.info")
    def test_options_post_keeps_only_hex_colours(self, mock_logger_info, mock_clear, mock_data_path, mock_info):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = os.path.join(temp_dir, "score.musicxml")
            mock_data_path.return_value = data_path
            mock_info.return_value = {
                "title": "Score", "composer": "Composer", "instruments": ["Piano"],
                "rhythm_range": [], "beat_division_options": [],
            }

            response = self.client.post(
                reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"}),
                {
                    "instruments": ["1"], "bars_at_a_time": "2", "beat_division": "",
                    "colorProfile": "custom",
                    "color_C": "#ff0000", "color_D": "red;}</style><script>alert(1)</script>",
                    "color_rhythm_crotchet": "#abc", "color_rhythm_quaver": "url(x)",
                    "color_octave_4": "#123456", "color_octave_5": "expression(1)",
                },
            )
            self.assertEqual(response.status_code, 302)
            with open(data_path + ".opts", encoding="utf-8") as opts_file:
                options = json.load(opts_file)

        self.assertEqual(options["figureNoteColours"], {"C": "#ff0000"})
        self.assertEqual(options["advanced_rhythm_colours"], {"crotchet": "#abc"})
        self.assertEqual(options["advanced_octave_colours"], {"4": "#123456"})

    def test_homepage_explains_an_unknown_host(self):
        with patch("talkingscoresapp.views.TSScore.from_url", side_effect=score_models.RemoteHostNotFound("no such host")):
            with patch.object(score_settings, "DEBUG", True), patch.object(views_module.logger, "warning"):
                response = self.client.post(reverse("index"), {"url": "http://nowhere.example/score.musicxml"}, follow=True)

        self.assertContains(response, "could not be found")
        self.assertNotContains(response, "private or local network address")

    def test_homepage_explains_a_refused_link(self):
        message = "The file at that link is larger than 10 MB."
        with patch("talkingscoresapp.views.TSScore.from_url", side_effect=score_models.RemoteFetchRefused(message)):
            with patch.object(score_settings, "DEBUG", True), patch.object(views_module.logger, "warning"):
                response = self.client.post(reverse("index"), {"url": "http://big.example/score.musicxml"}, follow=True)

        self.assertContains(response, message)

    def test_homepage_explains_a_failed_download(self):
        with patch("talkingscoresapp.views.TSScore.from_url", side_effect=requests.ConnectionError("reset")):
            with patch.object(score_settings, "DEBUG", True), patch.object(views_module.logger, "warning"):
                response = self.client.post(reverse("index"), {"url": "http://down.example/score.musicxml"}, follow=True)

        self.assertContains(response, "could not be downloaded")

    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_rejects_tunnelled_private_addresses(self, mock_get):
        # 6to4 and Teredo addresses carry an IPv4 address inside them.
        for address in ("2002:c0a8:101::", "2001:0:4136:e378:8000:63bf:3fff:fdd2"):
            addrinfo = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, 80, 0, 0))]
            with patch("talkingscoresapp.models.socket.getaddrinfo", return_value=addrinfo):
                with self.assertRaises(score_models.RemoteAddressNotAllowed, msg=address):
                    TSScore.from_url("http://scores.example/score.musicxml")
        mock_get.assert_not_called()

    @patch("talkingscoresapp.models.requests.Session.get")
    def test_from_url_reports_an_unknown_host(self, mock_get):
        with patch("talkingscoresapp.models.socket.getaddrinfo", side_effect=socket.gaierror):
            with self.assertRaises(score_models.RemoteHostNotFound):
                TSScore.from_url("http://nowhere.example/score.musicxml")
        with self.assertRaises(score_models.RemoteFetchRefused):
            TSScore.from_url("ftp://scores.example/score.musicxml")
        mock_get.assert_not_called()

    def test_state_treats_an_unusable_filename_as_missing(self):
        self.assertEqual(TSScore(id=VALID_ID, filename="..").state(), score_models.TSScoreState.FETCHING)
        self.assertEqual(TSScore(id=VALID_ID, filename=None).state(), score_models.TSScoreState.FETCHING)

    @patch("talkingscoresapp.views.TSScore.start_background_processing")
    @patch("talkingscoresapp.views.TSScore.state", return_value=score_models.TSScoreState.AWAITING_OPTIONS)
    def test_processing_page_sends_the_reader_to_set_up(self, mock_state, mock_start):
        options_url = reverse("options", kwargs={"id": VALID_ID, "filename": "score.musicxml"})

        response = self.client.get(reverse("process", kwargs={"id": VALID_ID, "filename": "score.musicxml"}))
        self.assertRedirects(response, options_url, fetch_redirect_response=False)

        status = self.client.get(reverse("process-status", kwargs={"id": VALID_ID, "filename": "score.musicxml"})).json()
        self.assertEqual(status["status"], "options_required")
        self.assertEqual(status["next_url"], options_url)
        mock_start.assert_not_called()

    def test_mxl_extraction_refuses_a_utf16_manifest_with_entities(self):
        container = (
            '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE c [<!ENTITY a "aaaa">]>'
            '<container><rootfiles><rootfile full-path="real/score.xml"/></rootfiles></container>'
        ).encode("utf-16")
        with tempfile.TemporaryDirectory() as temp_dir:
            mxl_path = os.path.join(temp_dir, "score.mxl")
            with zipfile.ZipFile(mxl_path, "w") as archive:
                archive.writestr("META-INF/container.xml", container)
                archive.writestr("first.xml", "<fallback/>")
                archive.writestr("real/score.xml", "<score-partwise/>")
            output_path = os.path.join(temp_dir, "score.musicxml")

            with patch.object(score_models.logger, "info"):
                score_models.extract_musicxml_from_mxl(mxl_path, output_path)

            with open(output_path, encoding="utf-8") as output:
                self.assertEqual(output.read(), "<fallback/>")

    def _locked_score(self, temp_dir):
        score = TSScore(id=VALID_ID, filename="score.musicxml")
        data_path = os.path.join(temp_dir, VALID_ID, "score.musicxml")
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        return score, data_path

    def test_refresh_raises_on_a_disk_error_and_keeps_ownership(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._locked_score(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path):
                self.assertTrue(score.acquire_generation_lock())
                with patch("talkingscoresapp.models.os.replace", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        score.refresh_generation_lock()
                self.assertTrue(score.refresh_generation_lock())
                self.assertFalse(glob.glob(data_path + ".lock.*.tmp"))
                score.release_generation_lock()

    def test_heartbeat_keeps_going_after_a_disk_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._locked_score(temp_dir)
            outcomes = iter([OSError("disk full"), True, True, True, True, True])
            with patch.object(score, "get_data_file_path", return_value=data_path), \
                    patch("talkingscoresapp.models.GENERATION_HEARTBEAT_SECONDS", 0.01), \
                    patch.object(score, "refresh_generation_lock", side_effect=lambda: _raise_or_return(next(outcomes, True))) as mock_refresh, \
                    patch.object(score.logger, "warning") as mock_warning:
                with score._generation_heartbeat():
                    time.sleep(0.1)
            self.assertGreaterEqual(mock_refresh.call_count, 2)
            mock_warning.assert_called()

    def test_heartbeat_stops_once_the_lock_is_lost(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._locked_score(temp_dir)
            with patch.object(score, "get_data_file_path", return_value=data_path), \
                    patch("talkingscoresapp.models.GENERATION_HEARTBEAT_SECONDS", 0.01), \
                    patch.object(score, "refresh_generation_lock", return_value=False) as mock_refresh:
                with score._generation_heartbeat():
                    time.sleep(0.1)
            self.assertEqual(mock_refresh.call_count, 1)

    def test_stale_takeover_leaves_one_owner(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score, data_path = self._locked_score(temp_dir)
            first = TSScore(id=VALID_ID, filename="score.musicxml")
            second = TSScore(id=VALID_ID, filename="score.musicxml")
            with patch.object(score, "get_data_file_path", return_value=data_path), \
                    patch.object(first, "get_data_file_path", return_value=data_path), \
                    patch.object(second, "get_data_file_path", return_value=data_path):
                self.assertTrue(score.acquire_generation_lock())
                stale_time = time.time() + score_models.GENERATION_LOCK_STALE_SECONDS + 1
                with patch("talkingscoresapp.models.time.time", return_value=stale_time), \
                        patch.object(first.logger, "warning"):
                    # Both see a stale lock; the file is renamed into place, never removed and recreated.
                    with patch("talkingscoresapp.models.remove_file_quietly", wraps=score_models.remove_file_quietly) as mock_remove:
                        self.assertTrue(first.acquire_generation_lock())
                    self.assertFalse(any(call.args[0] == data_path + ".lock" for call in mock_remove.call_args_list))
                self.assertFalse(second.acquire_generation_lock())
                self.assertFalse(score.refresh_generation_lock())
                self.assertTrue(first.refresh_generation_lock())
                self.assertFalse(glob.glob(data_path + ".lock.*.tmp"))
                first.release_generation_lock()
                self.assertFalse(os.path.exists(data_path + ".lock"))


class MidiFileTests(TestCase):
    """One MIDI file per range of bars, holding every part at its written speed."""

    TWO_PART_SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Flute</part-name></score-part>
    <score-part id="P2"><part-name>Cello</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key>
      <time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>
      <direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>90</per-minute></metronome></direction-type></direction>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note></measure>
    <measure number="2"><note><pitch><step>D</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note></measure>
    <measure number="3"><note><pitch><step>E</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note></measure>
  </part>
  <part id="P2">
    <measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key>
      <time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>F</sign><line>4</line></clef></attributes>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note></measure>
    <measure number="2"><note><pitch><step>G</step><octave>2</octave></pitch><duration>4</duration><type>whole</type></note></measure>
    <measure number="3"><note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note></measure>
  </part>
</score-partwise>
"""

    def _handler_in(self, temp_dir, query=None):
        from lib.midiHandler import MidiHandler

        folder = os.path.join(temp_dir, VALID_ID)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "score.musicxml"), "w", encoding="utf-8") as score_file:
            score_file.write(self.TWO_PART_SCORE)
        request = Mock()
        request.GET = query if query is not None else {}
        return MidiHandler(request, VALID_ID, "score.musicxml")

    def test_the_file_name_cannot_leave_the_score_folder(self):
        from lib.midiHandler import MidiHandler, safe_media_name

        handler = MidiHandler(Mock(), VALID_ID, "../../../../tmp/evil")
        folder = os.path.join(score_settings.MEDIA_ROOT, VALID_ID)
        self.assertEqual(os.path.dirname(os.path.abspath(handler.midi_path(1, 1))), os.path.abspath(folder))
        with self.assertRaises(ValueError):
            safe_media_name("..")
        with self.assertRaises(ValueError):
            safe_media_name("")

    @staticmethod
    def _tracks_with_notes(path):
        with open(path, "rb") as midi_file:
            data = midi_file.read()
        return data[:4], sum(1 for index in range(len(data) - 3) if data[index:index + 4] == b"MTrk")

    def test_a_range_is_written_once_and_holds_every_part(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                handler = self._handler_in(temp_dir)
                path = handler.make_midi_file(2, 3)
                self.assertTrue(path.endswith("score.musicxmls2e3.mid"))
                header, tracks = self._tracks_with_notes(path)
                self.assertEqual(header, b"MThd")
                self.assertGreaterEqual(tracks, 2)     # one track per part
                self.assertFalse(glob.glob(path + ".*.partial"))

                written_at = os.path.getmtime(path)
                self.assertEqual(handler.make_midi_file(2, 3), path)
                self.assertEqual(os.path.getmtime(path), written_at)

    def test_the_requested_range_comes_from_the_query(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                handler = self._handler_in(temp_dir, {"start": "1", "end": "2"})
                self.assertEqual(handler.requested_range(), (1, 2))
                self.assertTrue(handler.get_or_make_midi_file().endswith("s1e2.mid"))

    def test_the_whole_score_is_written_when_no_range_is_asked_for(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                handler = self._handler_in(temp_dir)
                self.assertTrue(handler.make_midi_file().endswith("s1e3.mid"))

    def test_a_written_range_is_served_without_reading_the_score_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                self._handler_in(temp_dir).make_midi_file(1, 2)
                second = self._handler_in(temp_dir)
                with patch("lib.midiHandler.converter.parse") as mock_parse:
                    self.assertTrue(second.make_midi_file(1, 2).endswith("s1e2.mid"))
                mock_parse.assert_not_called()

    def test_a_range_past_the_last_bar_writes_the_range_that_fits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                handler = self._handler_in(temp_dir)
                self.assertTrue(handler.make_midi_file(2, 900).endswith("s2e3.mid"))
                self.assertTrue(handler.make_midi_file(900, 950).endswith("s3e3.mid"))
                written = sorted(os.path.basename(path) for path in glob.glob(os.path.join(temp_dir, VALID_ID, "*.mid")))
                self.assertEqual(written, ["score.musicxmls2e3.mid", "score.musicxmls3e3.mid"])

    def test_a_failed_write_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                handler = self._handler_in(temp_dir)
                with patch("lib.midiHandler.stream.Score.write", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        handler.make_midi_file(1, 2)
                self.assertEqual(glob.glob(os.path.join(temp_dir, VALID_ID, "*.partial")), [])
                self.assertEqual(glob.glob(os.path.join(temp_dir, VALID_ID, "*.mid")), [])

    def test_writing_an_excerpt_leaves_the_repeats_in_the_score(self):
        """The descriptions are built from the same parsed score the excerpt comes from."""
        from music21 import bar, converter, stream as m21_stream

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                handler = self._handler_in(temp_dir)
                handler.score = converter.parse(os.path.join(temp_dir, VALID_ID, "score.musicxml"))
                measure = handler.score.parts[0].getElementsByClass(m21_stream.Measure)[1]
                measure.rightBarline = bar.Repeat(direction="end")
                handler.make_midi_file(1, 2)
                self.assertIsInstance(measure.rightBarline, bar.Repeat)


class StaleMidiCleanupTests(TestCase):
    """Files written for the old way of asking for audio are removed; current ones stay."""

    def test_only_files_that_no_longer_match_a_range_are_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = os.path.join(temp_dir, VALID_ID)
            os.makedirs(folder)
            names = [
                "score.musicxml",
                "score.musicxmls1e2.mid",          # a range the page still asks for
                "score.musicxmls1e2c0t100.mid",    # a speed and a click the browser now applies
                "score.musicxmlsel-1s1e2.mid",     # a selection of instruments
                "s0e0_upfront.generated",          # a flag file nothing reads now
                "tmpabc.partial",                  # a write that was abandoned
                "other.mid",                       # names no score in its folder
            ]
            for name in names:
                with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
                    handle.write("x")
            old = time.time() - 7200
            os.utime(os.path.join(folder, "tmpabc.partial"), (old, old))

            output = StringIO()
            with patch("talkingscoresapp.management.commands.cleanup_midi.MEDIA_ROOT", temp_dir):
                call_command("cleanup_midi", stdout=output)

            self.assertEqual(sorted(os.listdir(folder)), ["score.musicxml", "score.musicxmls1e2.mid"])
            self.assertIn("Removed 5 file(s); kept 1.", output.getvalue())

    def test_a_write_still_in_progress_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = os.path.join(temp_dir, VALID_ID)
            os.makedirs(folder)
            for name in ("score.musicxml", "tmpnow.partial"):
                with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
                    handle.write("x")

            output = StringIO()
            with patch("talkingscoresapp.management.commands.cleanup_midi.MEDIA_ROOT", temp_dir):
                call_command("cleanup_midi", stdout=output)

            self.assertIn("tmpnow.partial", os.listdir(folder))

    def test_a_dry_run_removes_nothing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = os.path.join(temp_dir, VALID_ID)
            os.makedirs(folder)
            for name in ("score.musicxml", "score.musicxmls1e2t50.mid"):
                with open(os.path.join(folder, name), "w", encoding="utf-8") as handle:
                    handle.write("x")

            output = StringIO()
            with patch("talkingscoresapp.management.commands.cleanup_midi.MEDIA_ROOT", temp_dir):
                call_command("cleanup_midi", "--dry-run", stdout=output)

            self.assertEqual(len(os.listdir(folder)), 2)
            self.assertIn("Would remove", output.getvalue())


class PlayerScriptTests(TestCase):
    """The reading of a MIDI file in the browser, checked with node when it is present."""

    def test_the_player_reads_midi_files_correctly(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        tests_dir = os.path.join(settings.BASE_DIR, "talkingscoresapp", "static", "js", "tests")
        test_files = sorted(glob.glob(os.path.join(tests_dir, "*.test.mjs")))
        self.assertTrue(test_files)
        result = subprocess.run([node, "--test"] + test_files, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_player_lines_up_the_parts_of_a_file_music21_wrote(self):
        """A file built by hand cannot stand in for one the score engine produced."""
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                from lib.midiHandler import MidiHandler

                folder = os.path.join(temp_dir, VALID_ID)
                os.makedirs(folder)
                shutil.copy(os.path.join(settings.BASE_DIR, "talkingscoresapp", "fixtures",
                                         "instrument-change.musicxml"),
                            os.path.join(folder, "score.musicxml"))
                request = Mock()
                request.GET = {}
                path = MidiHandler(request, VALID_ID, "score.musicxml").make_midi_file(1, 2)

            from lib.talkingscoreslib import Music21TalkingScore

            score = Music21TalkingScore(os.path.join(folder, "score.musicxml"))
            names = score.get_instruments()
            # The flute takes up the piccolo part way through, which is one part playing
            # two instruments rather than a third part.
            self.assertEqual(len(names), 2)

            reader = os.path.join(settings.BASE_DIR, "talkingscoresapp", "static", "js",
                                  "tests", "read-midi.mjs")
            result = subprocess.run([node, reader, path, str(len(names))],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            music = json.loads(result.stdout)
            self.assertEqual(len(music["parts"]), 2)
            # The top part plays C then A, the lower one C two octaves down twice.
            self.assertEqual(music["parts"][0], [72, 69])
            self.assertEqual(music["parts"][1], [48, 48])
            # Two bars of four four at the written speed, counted through to the barline.
            self.assertEqual(music["clicks"], 8)
            self.assertAlmostEqual(music["duration"], 4.0, places=3)

    def test_a_range_ending_in_rests_keeps_its_full_length(self):
        """The file stops at the last note, so the bars after it have to be marked."""
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("lib.midiHandler.MEDIA_ROOT", temp_dir):
                from lib.midiHandler import MidiHandler

                folder = os.path.join(temp_dir, VALID_ID)
                os.makedirs(folder)
                shutil.copy(os.path.join(settings.BASE_DIR, "talkingscoresapp", "fixtures",
                                         "rest-at-the-end.musicxml"),
                            os.path.join(folder, "score.musicxml"))
                request = Mock()
                request.GET = {}
                path = MidiHandler(request, VALID_ID, "score.musicxml").make_midi_file(1, 2)

            reader = os.path.join(settings.BASE_DIR, "talkingscoresapp", "static", "js",
                                  "tests", "read-midi.mjs")
            result = subprocess.run([node, reader, path, "1"], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            music = json.loads(result.stdout)
            # One note in the first bar, then a bar of rests that is still counted.
            self.assertEqual(music["parts"][0], [72])
            self.assertEqual(music["clicks"], 8)
            self.assertAlmostEqual(music["duration"], 4.0, places=3)


def _raise_or_return(outcome):
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome
