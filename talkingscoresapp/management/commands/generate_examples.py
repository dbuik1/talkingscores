from django.core.management.base import BaseCommand

from talkingscoresapp import library
from talkingscoresapp.models import TSScoreState
from talkingscoresapp.views import default_options, store_library_entry, write_options


class Command(BaseCommand):
    help = "Create the example talking scores the home page links to, so the first reader to open one does not wait."

    def handle(self, *args, **options):
        for example in library.examples():
            score = store_library_entry(example)
            if score.state() == TSScoreState.AWAITING_OPTIONS:
                write_options(score, default_options(score.info()))
            score.html(raise_errors=True)
            self.stdout.write(f"Created {example['title']}")
