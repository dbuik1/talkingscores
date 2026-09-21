#!/usr/bin/env python3
"""Scan this repository's user-facing text and code comments for copy that
should not reach a reader: rationale leaked into interface strings, marketing
register, negative parallelism, and comments that cite where an instruction came
from instead of stating the constraint.

Usage:
    python3 scripts/check_copy.py                 # every file the site ships
    python3 scripts/check_copy.py path [path ...] # only those files
    python3 scripts/check_copy.py --hook          # one file, named in the JSON on stdin

Exits 0 when clean and 1 when anything looks suspicious, printing each hit.
The general patterns live in check_user_copy.py beside this file; what is here
is how they are applied to a Django site whose templates carry inline scripts.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_user_copy  # noqa: E402

# Templates and scripts whose text renders for a reader.
COPY_FILES = [
    "talkingscoresapp/templates/*.html",
    "lib/talkingscore.html",
    "lib/beats.html",
    "talkingscoresapp/static/js/*.js",
    "lib/*.py",
    "talkingscoresapp/views.py",
    "talkingscoresapp/models.py",
]
# Source whose comments are checked.
COMMENT_FILES = [
    "lib/*.py", "lib/*.html",
    "talkingscoresapp/*.py",
    "talkingscoresapp/management/commands/*.py",
    "talkingscoresapp/static/js/*.js",
    "talkingscoresapp/static/js/tests/*.mjs",
    "talkingscoresapp/templates/*.html",
    "scripts/*.py",
]
# The change log is a record of what was said at the time, so it is annotated,
# never rewritten, and its older wording is not held to today's rules.
SKIPPED = {"talkingscoresapp/templates/change-log.html"}

# In a site about music, "the note that sounds" is a fact, not meta-commentary.
COPY_PATTERNS = [(p, r) for p, r in check_user_copy.COPY_COMPILED if "note that" not in p.pattern]
COMMENT_PATTERNS = check_user_copy.COMMENT_COMPILED

EMBEDDED = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
DOCTYPE = re.compile(r"<!DOCTYPE[^>]*>", re.I)
# Jinja and Django tags, and the values inside attributes, are code, not copy.
TEMPLATE_CODE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}|<[^>]*>", re.S)
JS_CODE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')


def blank_keeping_lines(text, pattern):
    """Replace each match with newlines only, so line numbers stay true."""
    return pattern.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def copy_lines(path, text):
    """The lines of text a reader could see, with everything else blanked."""
    if path.suffix == ".html":
        text = blank_keeping_lines(text, EMBEDDED)
        text = blank_keeping_lines(text, DOCTYPE)
        text = blank_keeping_lines(text, TEMPLATE_CODE)
        return text.splitlines()
    if path.suffix in (".js", ".mjs", ".py"):
        # Only quoted strings can reach a reader from a script or a view, and a
        # string without a space in it is a token or a symbol, not a sentence.
        lines = []
        for line in text.splitlines():
            if check_user_copy.COMMENT_LINE.match(line):
                lines.append("")
                continue
            lines.append(" ".join(s for s in JS_CODE.findall(line) if " " in s))
        return lines
    return text.splitlines()


def scan_copy(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    hits = []
    for lineno, line in enumerate(copy_lines(path, text), start=1):
        for pattern, reason in COPY_PATTERNS:
            if pattern.search(line):
                hits.append((path, lineno, reason, line.strip()))
    return hits


def scan_comments(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = check_user_copy.COMMENT_LINE.match(line)
        if not match:
            continue
        for pattern, reason in COMMENT_PATTERNS:
            if pattern.search(match.group(2)):
                hits.append((path, lineno, reason, line.strip()))
    return hits


def expand(globs):
    files = set()
    for pattern in globs:
        files.update(ROOT.glob(pattern))
    return {f for f in files if f.relative_to(ROOT).as_posix() not in SKIPPED}


def matching(path, globs):
    return any(path.match(str(ROOT / g)) for g in globs)


def scan(paths):
    hits = []
    for path in sorted(paths):
        if not path.is_file():
            continue
        if matching(path, COPY_FILES):
            hits.extend(scan_copy(path))
        if matching(path, COMMENT_FILES):
            hits.extend(scan_comments(path))
    return hits


def main(argv):
    args = argv[1:]
    if args and args[0] == "--hook":
        payload = json.load(sys.stdin)
        edited = (payload.get("tool_input") or {}).get("file_path")
        if not edited:
            return 0
        edited = Path(edited).resolve()
        if not edited.is_relative_to(ROOT) or edited.relative_to(ROOT).as_posix() in SKIPPED:
            return 0
        paths = {edited}
    elif args:
        paths = {Path(a).resolve() for a in args}
    else:
        paths = expand(COPY_FILES) | expand(COMMENT_FILES)

    hits = scan(paths)
    if not hits:
        print("No suspicious copy or comments found.")
        return 0
    print(f"Found {len(hits)} suspicious line(s):\n")
    for path, lineno, reason, line in hits:
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"  {shown}:{lineno}  [{reason}]")
        print(f"    {line}\n")
    # A hook exit of 2 hands the hits back to the editing session as feedback.
    return 2 if args and args[0] == "--hook" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
