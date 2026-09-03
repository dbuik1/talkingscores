import os
import re
import shutil
import time

from django.core.management.base import BaseCommand

from talkingscores.settings import MEDIA_ROOT

# A score folder is named for the score id: 64 lower-case hex digits.
SCORE_FOLDER_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class Command(BaseCommand):
    help = "Remove old generated score media folders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days",
            type=int,
            default=30,
            help="Remove score folders whose newest file is older than this many days.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be removed without deleting anything.",
        )

    def handle(self, *args, **options):
        older_than_days = options["older_than_days"]
        dry_run = options["dry_run"]
        cutoff = time.time() - (older_than_days * 24 * 60 * 60)

        if not os.path.isdir(MEDIA_ROOT):
            self.stdout.write(self.style.WARNING(f"Media root does not exist: {MEDIA_ROOT}"))
            return

        removed = 0
        skipped = 0

        for name in os.listdir(MEDIA_ROOT):
            path = os.path.join(MEDIA_ROOT, name)
            # Only score folders are removed; the media root also holds the log
            # and music21's own cache, which this command does not own.
            if not os.path.isdir(path) or not SCORE_FOLDER_PATTERN.match(name):
                skipped += 1
                continue

            newest_mtime = self._newest_mtime(path)
            if newest_mtime is None or newest_mtime > cutoff:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"Would remove {path}")
            else:
                shutil.rmtree(path)
                self.stdout.write(f"Removed {path}")
            removed += 1

        action = "Would remove" if dry_run else "Removed"
        self.stdout.write(self.style.SUCCESS(f"{action} {removed} folder(s); skipped {skipped}."))

    def _newest_mtime(self, path):
        newest = None
        for root, _dirs, files in os.walk(path):
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    mtime = os.path.getmtime(file_path)
                except OSError:
                    continue
                newest = mtime if newest is None else max(newest, mtime)
        return newest
