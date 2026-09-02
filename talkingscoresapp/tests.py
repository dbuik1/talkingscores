"""
Essential tests for Talking Scores - focused on critical issues.
"""

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from talkingscores import settings as score_settings
from talkingscoresapp.models import TSScore
from talkingscoresapp import models as score_models
from talkingscoresapp.management.commands import cleanup_media
from jinja2 import Environment, FileSystemLoader
from unittest.mock import patch, Mock
from io import StringIO
import tempfile
import os
import time
import json
import runpy
import socket
import threading
import zipfile

# Score ids are the SHA-256 of the file, so tests use a well-formed 64-digit id.
VALID_ID = "a" * 64
OTHER_ID = "b" * 64
REAL_THREAD = threading.Thread
PUBLIC_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


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
        policy = response["Content-Security-Policy"]
        self.assertIn("script-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertIn("upgrade-insecure-requests", policy)

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
        self.assertContains(response, 'Change Log')
        
    def test_contact_us_loads(self):
        """Test the contact us page loads correctly."""
        response = self.client.get(reverse('contact-us'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Contact Us')

    @patch("talkingscoresapp.views.TSScore.start_background_processing", return_value=True)
    @patch("talkingscoresapp.views.TSScore.state", return_value="processed")
    def test_processing_page_shows_live_status_region(self, mock_state, mock_start):
        response = self.client.get(
            reverse("process", kwargs={"id": VALID_ID, "filename": "score.musicxml"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, "Starting score generation")
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
        self.assertContains(response, "Try another score")
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
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as midi_file:
            midi_file.write(b"MThd")
            midi_path = midi_file.name

        mock_get_midi.return_value = midi_path

        try:
            response = self.client.get(
                reverse("midi", kwargs={"id": VALID_ID, "filename": "score.musicxml"}) + "?bsi=3&bpi=7&t=100&c=n"
            )
        finally:
            if "response" in locals():
                response.close()
            os.unlink(midi_path)

        self.assertEqual(response.status_code, 200)
        self.assertIn("audio/midi", response["Content-Type"])
        self.assertIn(".mid", response["Content-Disposition"])
        self.assertNotIn("Access-Control-Allow-Origin", response)

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
            "?bsi=x&bpi=7&t=100&c=n",
            "?bsi=3&bpi=7&start=8&end=4&t=100&c=n",
            "?bsi=3&bpi=7&t=999&c=n",
            "?bsi=3&bpi=7&t=100&c=bad",
            "?bsi=3&bpi=7&sel=everything&t=100&c=n",
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

    @patch("talkingscoresapp.views.TSScore.state")
    @patch("talkingscoresapp.views.TSScore.html")
    def test_html_download_strips_live_only_controls(self, mock_html, mock_state):
        mock_state.return_value = "processed"
        mock_html.return_value = """
            <html>
                <head><script src="//www.midijs.net/lib/midi.js"></script></head>
                <body>
                    <a href="#" id="stop-playback-btn">Stop Playback</a>
                    <div class="download-controls"><a href="/download/html/abc123/score.musicxml">Download HTML</a></div>
                    <div id="global-controls"><h2>Entire Score Playback</h2><div><a class="lnkPlay" data-base-url="/midis/abc123/score.musicxml?bsi=3">Play Score</a></div></div>
                    <h1>Music segment descriptions and playback</h1>
                    <div class="playback-controls"><select><option>100%</option></select></div>
                    <a class="lnkPlay" data-base-url="/midis/abc123/score.musicxml?bsi=3">Play All</a>
                    <p>Readable score text</p>
                </body>
            </html>
        """

        response = self.client.get(
            reverse("download-html", kwargs={"id": VALID_ID, "filename": "score.musicxml"})
        )
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Download HTML", content)
        self.assertNotIn("midijs.net", content)
        self.assertNotIn("data-base-url", content)
        self.assertNotIn('class="lnkPlay"', content)
        self.assertNotIn("Entire Score Playback", content)
        self.assertIn("Music segment descriptions", content)
        self.assertIn("Readable score text", content)

    def test_export_template_omits_download_and_midi_controls(self):
        env = Environment(loader=FileSystemLoader(os.path.join(os.getcwd(), "lib")))
        template = env.get_template("talkingscore.html")

        html = template.render({
            "export_mode": True,
            "export_theme": "dark",
            "inline_css": "",
            "download_html_url": "/download/html/abc123/score.musicxml",
            "basic_information": {"title": "Score", "composer": "Composer"},
            "preamble": {
                "time_signature": "4 4",
                "key_signature": "C major",
                "tempo": "100",
                "number_of_parts": 1,
            },
            "full_score_midis": {"selected_instruments_midis": {}},
            "music_segments": [],
            "general_summary": "",
            "parts_summary": [],
            "selected_part_names": [],
            "play_all": False,
            "play_selected": False,
            "play_unselected": False,
            "instruments": {},
            "part_names": [],
            "time_and_keys": {},
            "settings": {},
            "repetition_in_contexts": {},
            "immediate_repetition_contexts": {},
        })

        self.assertNotIn("Download HTML", html)
        self.assertNotIn("midijs.net", html)
        self.assertNotIn('class="lnkPlay"', html)
        self.assertNotIn("data-base-url", html)
        self.assertNotIn("Entire Score Playback", html)
        self.assertIn("Music segment descriptions</h1>", html)

    def test_export_template_can_inline_css(self):
        env = Environment(loader=FileSystemLoader(os.path.join(os.getcwd(), "lib")))
        template = env.get_template("talkingscore.html")

        html = template.render({
            "export_mode": True,
            "export_theme": "light",
            "inline_css": "body { color: red; }",
            "download_html_url": "",
            "basic_information": {"title": "Score", "composer": "Composer"},
            "preamble": {"time_signature": "4 4", "key_signature": "C major", "tempo": "100", "number_of_parts": 1},
            "full_score_midis": {"selected_instruments_midis": {}},
            "music_segments": [],
            "general_summary": "",
            "parts_summary": [],
            "selected_part_names": [],
            "play_all": False,
            "play_selected": False,
            "play_unselected": False,
            "instruments": {},
            "part_names": [],
            "time_and_keys": {},
            "settings": {},
            "repetition_in_contexts": {},
            "immediate_repetition_contexts": {},
        })

        self.assertIn("body { color: red; }", html)
        self.assertNotIn("127.0.0.1:8000/static/css/talkingscores.css", html)

    def test_live_template_uses_static_css_path(self):
        env = Environment(loader=FileSystemLoader(os.path.join(os.getcwd(), "lib")))
        template = env.get_template("talkingscore.html")

        html = template.render({
            "export_mode": False,
            "export_theme": None,
            "inline_css": "",
            "static_css_url": "/static/css/talkingscores.css",
            "download_html_url": "/download/html/abc123/score.musicxml",
            "basic_information": {"title": "Score", "composer": "Composer"},
            "preamble": {"time_signature": "4 4", "key_signature": "C major", "tempo": "100", "number_of_parts": 1},
            "full_score_midis": {"selected_instruments_midis": {}},
            "music_segments": [],
            "general_summary": "",
            "parts_summary": [],
            "selected_part_names": [],
            "play_all": False,
            "play_selected": False,
            "play_unselected": False,
            "instruments": {},
            "part_names": [],
            "time_and_keys": {},
            "settings": {},
            "repetition_in_contexts": {},
            "immediate_repetition_contexts": {},
        })

        self.assertIn('href="/static/css/talkingscores.css"', html)
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
        self.assertContains(response, "Select a valid choice")
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

                        self.assertIn("Error Generating Score", score.html(force_refresh=True))

    @patch("talkingscoresapp.models.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO)
    @patch("talkingscoresapp.models.Music21TalkingScore")
    @patch("talkingscoresapp.models.requests.get")
    def test_from_url_streams_remote_file_with_timeout(self, mock_get, mock_music21, mock_dns):
        class FakeResponse:
            status_code = 200

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

        mock_get.assert_called_once_with(
            "https://example.com/score.musicxml",
            timeout=score_models.REMOTE_FETCH_TIMEOUT,
            stream=True,
            allow_redirects=False,
            proxies=score_models.NO_PROXIES,
        )
        self.assertEqual(score.filename, "score.musicxml")
        mock_music21.assert_called()

    @patch("talkingscoresapp.models.socket.getaddrinfo", return_value=PUBLIC_ADDRINFO)
    @patch("talkingscoresapp.models.requests.get")
    def test_from_url_rejects_oversized_remote_file(self, mock_get, mock_dns):
        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=65536):
                yield b"123456"

        mock_get.return_value = FakeResponse()

        with patch.object(score_models, "MAX_REMOTE_SCORE_BYTES", 5):
            with self.assertRaises(ValueError):
                TSScore.from_url("https://example.com/score.musicxml")

    def test_from_url_rejects_unsupported_scheme(self):
        with self.assertRaises(ValueError):
            TSScore.from_url("file:///C:/temp/score.musicxml")

    @patch("talkingscoresapp.models.requests.get")
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

    @patch("talkingscoresapp.models.requests.get")
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
    @patch("talkingscoresapp.models.requests.get")
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
        env = Environment(loader=FileSystemLoader(os.path.join(os.getcwd(), "lib")), autoescape=True)
        template = env.get_template("talkingscore.html")

        html = template.render({
            "export_mode": True,
            "export_theme": "light",
            "inline_css": "body { color: red; }",
            "download_html_url": "",
            "basic_information": {"title": "<script>alert(1)</script>", "composer": "Composer"},
            "preamble": {"time_signature": "4 4", "key_signature": "C major", "tempo": "100", "number_of_parts": 1},
            "full_score_midis": {"selected_instruments_midis": {}},
            "music_segments": [],
            "general_summary": "",
            "parts_summary": [],
            "selected_part_names": [],
            "play_all": False,
            "play_selected": False,
            "play_unselected": False,
            "instruments": {},
            "part_names": [],
            "time_and_keys": {},
            "settings": {},
            "repetition_in_contexts": {},
            "immediate_repetition_contexts": {},
        })

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("body { color: red; }", html)

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
            old_dir = os.path.join(temp_dir, "old-score")
            new_dir = os.path.join(temp_dir, "new-score")
            os.makedirs(old_dir)
            os.makedirs(new_dir)
            old_file = os.path.join(old_dir, "score.musicxml")
            new_file = os.path.join(new_dir, "score.musicxml")
            with open(old_file, "w", encoding="utf-8") as file:
                file.write("old")
            with open(new_file, "w", encoding="utf-8") as file:
                file.write("new")
            old_time = time.time() - (40 * 24 * 60 * 60)
            os.utime(old_file, (old_time, old_time))

            out = StringIO()
            with patch.object(cleanup_media, "MEDIA_ROOT", temp_dir):
                call_command("cleanup_media", "--older-than-days", "30", "--dry-run", stdout=out)
                self.assertTrue(os.path.isdir(old_dir))
                self.assertIn("Would remove", out.getvalue())

                call_command("cleanup_media", "--older-than-days", "30", stdout=StringIO())

            self.assertFalse(os.path.exists(old_dir))
            self.assertTrue(os.path.exists(new_dir))


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
                later = time.time() + score_models.GENERATION_LOCK_STALE_SECONDS + 1
                with patch("talkingscoresapp.models.time.time", return_value=later):
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
