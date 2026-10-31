"""Reading a PDF or photo of printed music into a score.

An uploaded page is kept under MEDIA_ROOT/readings/<sha256 of the file>/, a
reader program (settings.SCORE_READER_COMMAND) turns it into MusicXML on a
background thread, and that MusicXML becomes an ordinary score. The reading's
status file names the score once it exists, so the reading page can open it.
"""

import glob
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time

from django.conf import settings
from django.core.files import File

from talkingscores.settings import MEDIA_ROOT
from talkingscoresapp.models import SCORE_ID_PATTERN, TSScore, hashfile, remove_file_quietly

logger = logging.getLogger("TSScore")

# The first bytes of each kind of page the readers accept. The upload's name
# alone is not trusted, since the file is handed to another program.
PAGE_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}
ALLOWED_PAGE_EXTENSIONS = tuple(PAGE_SIGNATURES)
MAX_UPLOADED_PAGE_BYTES = 20 * 1024 * 1024

READING_MESSAGE = "Reading the notes on the page"
WAITING_MESSAGE = "Waiting for another score to finish reading"
WRITING_MESSAGE = "Writing out the bars"
READ_FAILED_MESSAGE = (
    "No music could be read from this file. A sharp, evenly lit photo or a PDF of "
    "printed music reads best."
)

_reader_slots = None
_reader_slots_guard = threading.Lock()


def reader_is_set_up():
    return bool(settings.SCORE_READER_COMMAND)


def page_extension(name):
    return os.path.splitext(name or "")[1].lower()


def is_page_file(name):
    return page_extension(name) in ALLOWED_PAGE_EXTENSIONS


def has_page_signature(uploaded_file, extension):
    uploaded_file.seek(0)
    head = uploaded_file.read(16)
    uploaded_file.seek(0)
    return any(head.startswith(signature) for signature in PAGE_SIGNATURES.get(extension, ()))


def reader_slots():
    global _reader_slots
    with _reader_slots_guard:
        if _reader_slots is None:
            _reader_slots = threading.BoundedSemaphore(max(1, settings.SCORE_READER_CONCURRENCY))
        return _reader_slots


class ImageReading(object):

    def __init__(self, id):
        if not SCORE_ID_PATTERN.match(id or ""):
            raise ValueError("Reading id must be 64 lower-case hex digits.")
        self.id = id
        self.folder = os.path.join(MEDIA_ROOT, "readings", id)

    @classmethod
    def from_uploaded_file(cls, uploaded_file):
        uploaded_file.seek(0)
        reading = cls(hashfile(uploaded_file, hashlib.sha256()))
        os.makedirs(reading.folder, exist_ok=True)
        page_path = reading.page_path(page_extension(uploaded_file.name))
        if not os.path.exists(page_path):
            uploaded_file.seek(0)
            with tempfile.NamedTemporaryFile(dir=reading.folder, delete=False) as temp_page:
                for chunk in uploaded_file.chunks():
                    temp_page.write(chunk)
            os.replace(temp_page.name, page_path)
        name = os.path.splitext(os.path.basename(uploaded_file.name))[0]
        reading._write_json("name.json", {"name": name})
        return reading

    def page_path(self, extension=None):
        if extension:
            return os.path.join(self.folder, "page" + extension)
        found = sorted(glob.glob(os.path.join(self.folder, "page.*")))
        return found[0] if found else None

    def exists(self):
        return self.page_path() is not None

    def name(self):
        return self._read_json("name.json").get("name") or "score"

    def status(self):
        status = self._read_json("status.json")
        return status or {"status": "pending", "message": READING_MESSAGE}

    def clear_status(self):
        remove_file_quietly(os.path.join(self.folder, "status.json"))

    def _write_status(self, status, message, **extra):
        self._write_json("status.json", {"status": status, "message": message, "updated": time.time(), **extra})

    def _read_json(self, name):
        try:
            with open(os.path.join(self.folder, name), encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_json(self, name, data):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.folder, delete=False) as handle:
            json.dump(data, handle)
        os.replace(handle.name, os.path.join(self.folder, name))

    # A reading holds a lock file while its thread runs. A server restart kills
    # the thread without removing the file, so a lock older than the reader's
    # time limit plus a margin is taken over.
    def _lock_path(self):
        return os.path.join(self.folder, "lock")

    def _acquire_lock(self):
        lock_path = self._lock_path()
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock_path)
            except OSError:
                return False
            if age < settings.SCORE_READER_TIMEOUT + 120:
                return False
            remove_file_quietly(lock_path)
            return self._acquire_lock()
        os.close(descriptor)
        return True

    def _release_lock(self):
        remove_file_quietly(self._lock_path())

    def is_running(self):
        return os.path.exists(self._lock_path())

    def start(self):
        """Read the page on a background thread unless it is read, or being read, already."""
        if self.status().get("status") == "complete" or not self._acquire_lock():
            return False
        self._write_status("reading", READING_MESSAGE)
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def _read(self):
        try:
            slots = reader_slots()
            if not slots.acquire(blocking=False):
                self._write_status("reading", WAITING_MESSAGE)
                slots.acquire()
            try:
                self._write_status("reading", READING_MESSAGE)
                musicxml_path = self._run_reader()
            finally:
                slots.release()
            self._write_status("reading", WRITING_MESSAGE)
            score = self._make_score(musicxml_path)
            self._write_status("complete", WRITING_MESSAGE, score_id=score.id, score_filename=score.filename)
        except Exception:
            logger.exception(f"Reading {self.id} from an image failed")
            self._write_status("failed", READ_FAILED_MESSAGE)
        finally:
            self._release_lock()

    def _run_reader(self):
        page = self.page_path()
        work = tempfile.mkdtemp(prefix="reading-", dir=self.folder)
        try:
            work_page = os.path.join(work, "page" + page_extension(page))
            shutil.copyfile(page, work_page)
            values = {"image": work_page, "workdir": work}
            command = [part.format(**values) for part in settings.SCORE_READER_COMMAND]
            finished = subprocess.run(command, cwd=work, capture_output=True, text=True,
                                      timeout=settings.SCORE_READER_TIMEOUT)
            if finished.returncode != 0:
                raise RuntimeError(f"Reader exited {finished.returncode}: {finished.stderr[-800:]}")
            found = sorted(glob.glob(os.path.join(work, settings.SCORE_READER_OUTPUT), recursive=True))
            if not found:
                raise RuntimeError(f"Reader wrote no file matching {settings.SCORE_READER_OUTPUT}")
            output = os.path.join(self.folder, "read" + page_extension(found[0]))
            shutil.copyfile(found[0], output)
            return output
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _make_score(self, musicxml_path):
        extension = page_extension(musicxml_path)
        with open(musicxml_path, "rb") as handle:
            score = TSScore.from_uploaded_file(File(handle, name=self.name() + extension))
        score.mark_read_from_image()
        return score
