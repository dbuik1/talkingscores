"""
Essential tests for Talking Scores - focused on critical issues.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.core.management import call_command
from talkingscoresapp.models import TSScore
from talkingscoresapp import models as score_models
from talkingscoresapp.management.commands import cleanup_media
from jinja2 import Environment, FileSystemLoader
from unittest.mock import patch
from io import StringIO
import tempfile
import os
import time


class SecurityTests(TestCase):
    """Security-focused test cases."""
    
    def test_file_path_traversal_prevention(self):
        """Test that file path traversal attacks are prevented."""
        malicious_names = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\config\\sam", 
            "test/../../../secret.txt",
            "/etc/passwd",
            "\\windows\\system32\\config\\sam"
        ]
        
        for malicious_name in malicious_names:
            score = TSScore(id="test123", filename=malicious_name)
            path = score.get_data_file_path()
            
            # Ensure the path is within the expected directory structure
            self.assertIn("test123", path)
            # Most importantly: ensure no path traversal characters remain
            self.assertNotIn("..", path)
            self.assertNotIn("/etc/", path)
            self.assertNotIn("\\windows\\", path.lower())


class BasicFunctionalityTests(TestCase):
    """Tests for basic page loads."""
    
    def setUp(self):
        self.client = Client()
        
    def test_homepage_loads(self):
        """Ensure the main page works."""
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Talking Scores')
        
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

    @patch("talkingscoresapp.views.TSScore.state")
    def test_processing_page_shows_live_status_region(self, mock_state):
        mock_state.return_value = "fetching"

        response = self.client.get(
            reverse("process", kwargs={"id": "abc123", "filename": "score.musicxml"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, "Starting score generation")


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
                reverse("midi", kwargs={"id": "abc123", "filename": "score.musicxml"})
            )
        finally:
            if "response" in locals():
                response.close()
            os.unlink(midi_path)

        self.assertEqual(response.status_code, 200)
        self.assertIn("audio/midi", response["Content-Type"])
        self.assertIn(".mid", response["Content-Disposition"])
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    @patch("talkingscoresapp.views.TSScore.state")
    @patch("talkingscoresapp.views.TSScore.html")
    def test_html_download(self, mock_html, mock_state):
        mock_state.return_value = "processed"
        mock_html.return_value = "<html><body>Score</body></html>"

        response = self.client.get(
            reverse("download-html", kwargs={"id": "abc123", "filename": "score.musicxml"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn("score-talking-score.html", response["Content-Disposition"])
        self.assertContains(response, "Score")
        mock_html.assert_called_once_with(export_theme=None, export_mode=True)

    @patch("talkingscoresapp.views.TSScore.state")
    @patch("talkingscoresapp.views.TSScore.html")
    def test_html_download_passes_valid_theme(self, mock_html, mock_state):
        mock_state.return_value = "processed"
        mock_html.return_value = "<html><body>Score</body></html>"

        response = self.client.get(
            reverse("download-html", kwargs={"id": "abc123", "filename": "score.musicxml"}) + "?theme=dark"
        )

        self.assertEqual(response.status_code, 200)
        mock_html.assert_called_once_with(export_theme="dark", export_mode=True)

    @patch("talkingscoresapp.views.TSScore.state")
    @patch("talkingscoresapp.views.TSScore.html")
    def test_html_download_discards_invalid_theme(self, mock_html, mock_state):
        mock_state.return_value = "processed"
        mock_html.return_value = "<html><body>Score</body></html>"

        response = self.client.get(
            reverse("download-html", kwargs={"id": "abc123", "filename": "score.musicxml"}) + "?theme=bad"
        )

        self.assertEqual(response.status_code, 200)
        mock_html.assert_called_once_with(export_theme=None, export_mode=True)

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
            reverse("download-html", kwargs={"id": "abc123", "filename": "score.musicxml"})
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
            reverse("process-status", kwargs={"id": "abc123", "filename": "score.musicxml"})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processing")
        mock_start.assert_called_once()


class CacheAndMaintenanceTests(TestCase):
    def test_score_logger_configuration_is_idempotent(self):
        handler_count = len(score_models.logger.handlers)

        score_models.configure_score_logger()

        self.assertEqual(len(score_models.logger.handlers), handler_count)

    def test_html_cache_is_reused_when_fresh(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score = TSScore(id="abc123", filename="score.musicxml")
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

    def test_html_can_raise_generation_errors_for_background_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            score = TSScore(id="abc123", filename="score.musicxml")
            data_path = os.path.join(temp_dir, "abc123", "score.musicxml")
            os.makedirs(os.path.dirname(data_path), exist_ok=True)
            with open(data_path, "w", encoding="utf-8") as data_file:
                data_file.write("<score-partwise></score-partwise>")

            with patch.object(score, "get_data_file_path", return_value=data_path):
                with patch("talkingscoresapp.models.Music21TalkingScore", side_effect=ValueError("bad score")):
                    with patch.object(score.logger, "info"), patch.object(score.logger, "exception"):
                        with self.assertRaises(ValueError):
                            score.html(force_refresh=True, raise_errors=True)

                        self.assertIn("Error Generating Score", score.html(force_refresh=True))

    @patch("talkingscoresapp.models.Music21TalkingScore")
    @patch("talkingscoresapp.models.requests.get")
    def test_from_url_streams_remote_file_with_timeout(self, mock_get, mock_music21):
        class FakeResponse:
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
        )
        self.assertEqual(score.filename, "score.musicxml")
        mock_music21.assert_called()

    @patch("talkingscoresapp.models.requests.get")
    def test_from_url_rejects_oversized_remote_file(self, mock_get):
        class FakeResponse:
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
