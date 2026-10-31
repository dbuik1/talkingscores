"""Run one score reader on one page and keep what it writes.

Readers are described in a TOML file (see engines.example.toml). Most are
command-line programs: the page is copied into an empty folder, the command
runs there, and the file it leaves (or what it prints) is kept. Flat is a
web service and is called directly.
"""

import base64
import os
import shutil
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import requests

DEFAULT_TIMEOUT = 900
FLAT_API = "https://api.flat.io/v2"


@dataclass
class Engine:
    name: str
    kind: str = "command"
    command: list = field(default_factory=list)
    input: str = "image"        # image or pdf
    output: str = "stdout"      # a glob inside the work folder, or stdout
    suffix: str = ".musicxml"   # file type of printed output
    extract: str = ""           # kern or abc: drop log lines printed before the music
    timeout: int = DEFAULT_TIMEOUT
    env: dict = field(default_factory=dict)


@dataclass
class Result:
    ok: bool
    seconds: float
    output: Path | None = None
    error: str = ""


def load_engines(config_path):
    with open(config_path, "rb") as handle:
        config = tomllib.load(handle)
    return {name: Engine(name=name, **spec) for name, spec in config.get("engines", {}).items()}


def pick_input(engine, item):
    if engine.input == "pdf" and item.pdf is not None:
        return item.pdf
    return item.image


def run(engine, item, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        if engine.kind == "flat":
            output = run_flat(engine, item, out_dir)
        else:
            output = run_command(engine, item, out_dir)
    except Exception as error:  # a reader crashing on one page is a result, not a stop
        return Result(False, time.monotonic() - started, None, f"{type(error).__name__}: {error}"[:500])
    return Result(True, time.monotonic() - started, output)


def run_command(engine, item, out_dir):
    source = pick_input(engine, item)
    with tempfile.TemporaryDirectory(prefix=f"omr-{engine.name}-") as workdir:
        work = Path(workdir)
        page = work / f"{item.key}{source.suffix}"
        shutil.copyfile(source, page)
        values = {"image": str(page), "workdir": str(work), "stem": item.key}
        command = [os.path.expanduser(part.format(**values)) for part in engine.command]
        env = {**os.environ, **{key: os.path.expanduser(str(value)) for key, value in engine.env.items()}}
        finished = subprocess.run(command, cwd=work, env=env, capture_output=True,
                                  text=True, timeout=engine.timeout)
        if finished.returncode != 0:
            raise RuntimeError(f"exit {finished.returncode}: {finished.stderr.strip()[-400:]}")
        if engine.output == "stdout":
            text = extract_music(finished.stdout, engine.extract)
            if not text.strip():
                raise RuntimeError("printed no music")
            target = out_dir / f"{item.key}{engine.suffix}"
            target.write_text(text, encoding="utf-8")
            return target
        found = sorted(work.glob(engine.output.format(**values)))
        if not found:
            raise RuntimeError(f"wrote no file matching {engine.output}")
        target = out_dir / f"{item.key}{found[0].suffix}"
        shutil.copyfile(found[0], target)
        return target


def extract_music(text, kind):
    """Keep the music from printed output that may start with progress lines."""
    lines = text.splitlines()
    starts = {"kern": lambda line: line.startswith("**"),
              "abc": lambda line: line.startswith("X:")}
    if kind in starts:
        for index, line in enumerate(lines):
            if starts[kind](line):
                return "\n".join(lines[index:]) + "\n"
        return ""
    return text


def run_flat(engine, item, out_dir):
    token = os.environ.get("FLAT_TOKEN")
    if not token:
        raise RuntimeError("FLAT_TOKEN is not set")
    headers = {"Authorization": f"Bearer {token}"}
    source = pick_input(engine, item)
    job = requests.post(f"{FLAT_API}/omr/jobs", headers=headers, timeout=60,
                        json={"output": "musicxml", "idempotencyKey": f"bench-{item.key}"})
    job.raise_for_status()
    job_id = job.json()["id"]
    upload = requests.post(f"{FLAT_API}/omr/jobs/{job_id}/files", headers=headers, timeout=120,
                           json={"file": base64.b64encode(source.read_bytes()).decode(),
                                 "filename": source.name})
    upload.raise_for_status()
    requests.post(f"{FLAT_API}/omr/jobs/{job_id}/start", headers=headers, timeout=60).raise_for_status()
    deadline = time.monotonic() + engine.timeout
    while True:
        status = requests.get(f"{FLAT_API}/omr/jobs/{job_id}", headers=headers,
                              params={"wait": 25}, timeout=60)
        status.raise_for_status()
        state = status.json().get("status")
        if state == "done":
            break
        if state in ("error", "canceled", "awaitingInput"):
            raise RuntimeError(f"Flat job {job_id} ended as {state}: {status.json().get('errorMessage', '')}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Flat job {job_id} still {state}")
    export = requests.get(f"{FLAT_API}/omr/jobs/{job_id}/exports/musicxml", headers=headers, timeout=120)
    export.raise_for_status()
    target = Path(out_dir) / f"{item.key}.musicxml"
    target.write_bytes(export.content)
    return target
