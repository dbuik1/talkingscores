# Talking Scores

A separate version of
[Talking Scores by Ben Timms](https://github.com/bentimms/talkingscores), which
turns a MusicXML score into a talking score: bars written out as words, with
playback of any range of bars in the browser. The original is still running;
this version carries changes that have not been merged into it, among them the
reader page, styles, downloads, sampled playback and reading aloud listed on
the change log page.

The code is released under the MIT licence in `LICENCE.txt`: the original is
copyright 2019 Ben Timms, and the changes in this version are copyright
2025-2026 David Buik. Both notices stay with every copy of this code.

## Prerequisites

1. A working Python 3 installation.
1. On Windows, Python 3.12 is recommended for this project:
   ```
   py -3.12 --version
   ```

## Installation

1. Create a virtual environment for the python requirements
   ```powershell
   py -3.12 -m venv venv
   ```
1. Install the required python modules
   ```powershell
   .\venv\Scripts\python.exe -m pip install --upgrade pip
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

## Running a server

1. Ensure the virtual environment is active.
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
1. Run the local Django server.
   ```powershell
   python .\manage.py runserver
   ```

## Maintenance

Remove old generated score files and MIDI caches with:

```powershell
python .\manage.py cleanup_media --older-than-days 30 --dry-run
python .\manage.py cleanup_media --older-than-days 30
```

Use `--dry-run` first to inspect what would be deleted.

The talking score page asks for one MIDI file per range of bars. Files written before
that, whose names carry a selection of instruments, a speed or a click setting,
are no longer asked for. Remove them with:

```powershell
python .\manage.py cleanup_midi --dry-run
python .\manage.py cleanup_midi
```

It is safe to run while the site is up: a half-written file is left alone until
an hour has passed, by which time no request can still be writing it.

## OpenScore catalogue

`talkingscoresapp/data/openscore.json` lists every score the "Find a score"
page can search: one entry per .mxl file in OpenScore's Lieder and String
Quartets repositories on GitHub, with a raw file URL the site fetches when a
reader opens one. Rebuild it after OpenScore adds scores:

```bash
git clone --filter=blob:none https://github.com/OpenScore/Lieder.git
git clone --filter=blob:none --no-checkout https://github.com/OpenScore/StringQuartets.git
python3 scripts/build_openscore_index.py --lieder Lieder --string-quartets StringQuartets
```

Commit the resulting `openscore.json`.

## Environment settings

`DJANGO_DEBUG` is off unless set, and with debug off the server refuses to start without `DJANGO_SECRET_KEY`. For local development and the test suite, turn debug on:

```powershell
$env:DJANGO_DEBUG = "true"
python .\manage.py test
```

The player that sounds a range of bars, and the voice that reads bars aloud, run in
the browser, so their own tests run under Node rather than Django. The Django suite runs them too when `node` is on
the path; to run them alone:

```
node --test talkingscoresapp/static/js/tests/*.test.mjs
```

The player sounds the notes with sampled instruments: the spessasynth_lib
synthesizer, vendored under `talkingscoresapp/static/js/vendor/`, playing the
GeneralUser GS sound bank in `talkingscoresapp/static/sound/`. Both are served
from this site, and their licences sit beside them. To take a newer release of
the synthesizer:

```
scripts/build_synth.sh
```

The words a reader sees, and the code comments, are checked for wording that
belongs in a commit message rather than on the page. The Django suite runs the
check; to run it alone:

```
python3 scripts/check_copy.py
```

In production, set:

```powershell
$env:DJANGO_SECRET_KEY = "replace-this"
$env:DJANGO_DEBUG = "false"
$env:DJANGO_ALLOWED_HOSTS = "www.example.com,127.0.0.1"
```

## Railway deployment

If you deploy this repo on Railway:

1. Use the `master` branch.
2. Set these environment variables:
   ```powershell
   DJANGO_SECRET_KEY=replace-this
   DJANGO_DEBUG=false
   DJANGO_ALLOWED_HOSTS=your-domain.com,talkingscores.davidbuik.com
   DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.com,https://talkingscores.davidbuik.com
   ```
3. Attach persistent storage and point `MEDIA_ROOT` at it if you want uploaded files, generated HTML, and MIDI files to survive restarts.
4. Let Railway use the `Procfile` in the repo root, which collects static assets, applies migrations, and starts Gunicorn:
   ```text
   python manage.py collectstatic --noinput && python manage.py migrate && gunicorn talkingscores.wsgi:application --bind 0.0.0.0:$PORT
   ```
5. Static files are served by WhiteNoise, so Railway does not need a separate static-file service.

If you need the app to keep generated files reliably, do not use an ephemeral filesystem only.

## macOS/Linux notes

If you are not on Windows, create and activate the same `venv` folder with:

```
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python ./manage.py runserver
```


