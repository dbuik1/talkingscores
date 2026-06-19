# Talking Scores

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

## Environment settings

For local development, defaults are provided. In production, set:

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


