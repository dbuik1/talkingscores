"""Runs cleanup_media and cleanup_midi on a schedule inside the web server.

Railway runs only the web process, so nothing else would call the cleanup
commands, and the volume fills. Every server process starts this thread; a lock
file on the volume lets one of them run the commands, and a stamp file records
when they last ran, so a restart does not run them again early.
"""

import fcntl
import logging
import os
import threading
import time

from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger("TSScore")

CHECK_EVERY_SECONDS = 3600
_started = False
_started_guard = threading.Lock()


def _stamp_path():
    return os.path.join(settings.MEDIA_ROOT, ".cleanup-last-run")


def run_if_due(every_hours, now=None):
    """Run the cleanup commands when the last run was at least every_hours ago. Returns whether they ran."""
    now = time.time() if now is None else now
    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    with open(os.path.join(settings.MEDIA_ROOT, ".cleanup.lock"), "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        try:
            last = os.path.getmtime(_stamp_path())
        except OSError:
            last = 0
        if now - last < every_hours * 3600:
            return False
        with open(_stamp_path(), "w"):
            pass
        os.utime(_stamp_path(), (now, now))
        for command in ("cleanup_media", "cleanup_midi"):
            try:
                call_command(command)
            except Exception:
                logger.exception(f"Scheduled {command} failed")
        return True


def start():
    """Start the schedule once per process, unless DJANGO_CLEANUP_EVERY_HOURS is 0."""
    global _started
    every_hours = settings.CLEANUP_EVERY_HOURS
    if every_hours <= 0:
        return
    with _started_guard:
        if _started:
            return
        _started = True

    def loop():
        while True:
            try:
                run_if_due(every_hours)
            except Exception:
                logger.exception("Scheduled cleanup could not run")
            time.sleep(CHECK_EVERY_SECONDS)

    threading.Thread(target=loop, daemon=True, name="cleanup-schedule").start()
