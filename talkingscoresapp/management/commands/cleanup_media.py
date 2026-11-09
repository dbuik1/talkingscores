import os
import re
import shutil
import time

from django.core.management.base import BaseCommand

from talkingscores.settings import MEDIA_ROOT
from talkingscoresapp import sharing

# A score folder is named for the score id: 64 lower-case hex digits.
SCORE_FOLDER_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class Command(BaseCommand):
    help = "Remove old generated score media folders and uploaded pages."

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
        # A listed upload cannot be fetched again, so removing its folder would
        # take it out of Find a score. Listed scores are kept however old.
        listed = {record["id"] for _code, record in sharing.listed_scores(MEDIA_ROOT)}

        # Uploaded PDFs and photos are kept per reading under readings/, named
        # the same way as score folders, and age out the same way.
        readings_root = os.path.join(MEDIA_ROOT, "readings")
        candidates = [(MEDIA_ROOT, name) for name in os.listdir(MEDIA_ROOT)]
        if os.path.isdir(readings_root):
            candidates += [(readings_root, name) for name in os.listdir(readings_root)]

        for parent, name in candidates:
            path = os.path.join(parent, name)
            # Only score and reading folders are removed here; the media root also
            # holds the log, the link records and music21's cache; the records and
            # the cache are pruned below.
            if not os.path.isdir(path) or not SCORE_FOLDER_PATTERN.match(name) or name in listed:
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

        # A link to an upload stops working once its folder has gone, and its
        # record and name would otherwise stay on the disk for good.
        forgotten = sharing.forget_abandoned(MEDIA_ROOT, dry_run=dry_run)
        self.stdout.write(f"{action} {len(forgotten)} link record(s) of uploads no longer stored.")

        # music21 keeps a parsed copy of every score it opens and never removes one.
        cached = self._remove_old_files(os.path.join(MEDIA_ROOT, "music21"), cutoff, dry_run)
        self.stdout.write(f"{action} {cached} file(s) from music21's cache.")

    def _remove_old_files(self, folder, cutoff, dry_run):
        count = 0
        for root, _dirs, files in os.walk(folder):
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    if os.path.getmtime(file_path) > cutoff:
                        continue
                    if not dry_run:
                        os.remove(file_path)
                except OSError:
                    continue
                count += 1
        return count

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
