import os
import re

from django.core.management.base import BaseCommand

from talkingscores.settings import MEDIA_ROOT

# A current file is named for the score and the range of bars it holds. Anything
# else ending in .mid was written for a selection of instruments, a speed and a
# click setting the browser now applies itself, so nothing asks for it again.
CURRENT_MIDI = re.compile(r"s\d+e\d+\.mid$")
SCORE_SUFFIXES = (".xml", ".musicxml", ".mxl")


class Command(BaseCommand):
    help = "Remove MIDI files that no longer match how the reading page asks for audio."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be removed without deleting anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if not os.path.isdir(MEDIA_ROOT):
            self.stdout.write(self.style.WARNING(f"Media root does not exist: {MEDIA_ROOT}"))
            return

        removed = 0
        kept = 0
        for folder in sorted(os.listdir(MEDIA_ROOT)):
            path = os.path.join(MEDIA_ROOT, folder)
            if not os.path.isdir(path):
                continue
            for name in sorted(os.listdir(path)):
                if not self._is_stale(path, name):
                    kept += name.lower().endswith(".mid")
                    continue
                file_path = os.path.join(path, name)
                if dry_run:
                    self.stdout.write(f"Would remove {file_path}")
                else:
                    try:
                        os.remove(file_path)
                    except OSError as error:
                        self.stdout.write(self.style.WARNING(f"Could not remove {file_path}: {error}"))
                        continue
                    self.stdout.write(f"Removed {file_path}")
                removed += 1

        action = "Would remove" if dry_run else "Removed"
        self.stdout.write(self.style.SUCCESS(f"{action} {removed} file(s); kept {kept}."))

    def _is_stale(self, folder_path, name):
        lowered = name.lower()
        if lowered.endswith(".partial") or lowered.endswith(".generated"):
            return True
        if not lowered.endswith(".mid"):
            return False
        for score_name in os.listdir(folder_path):
            if score_name.lower().endswith(SCORE_SUFFIXES) and name.startswith(score_name):
                return not CURRENT_MIDI.match(name[len(score_name):])
        # A MIDI file naming no score in its folder is left over from a score that has gone.
        return True
