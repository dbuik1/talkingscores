"""Short links to a talking score: /s/<name>.

A score from the library or a web address is named after its title, such as
/s/ode-to-joy, with -2, -3 and so on when another score has that title. An
uploaded score is named with three music words, such as /s/presto-cello-fugue,
so the link says nothing about what was uploaded. A screen reader reads either
as words. Names are stored under MEDIA_ROOT/links/names, each holding the code
it opens: the first ten hex digits of the score's id, which is the SHA-256 of
its file. That code works as a link too, so links made before names keep working.

Each time options are saved, a record is written under MEDIA_ROOT/links: the
score's id and file name, where the file came from and the options. The score
folders are cleaned up after a while, and the links folder is not, so a link to
a score that came from a web address or the library still opens: the file is
fetched again and the options put back. A link to an uploaded file works only
while that file is stored; once it has gone, its three words can name another
upload.
"""

import json
import os
import re
import secrets

from django.utils.text import slugify

from talkingscores.settings import MEDIA_ROOT
from talkingscoresapp import share_words

SHORT_CODE_LENGTH = 10
SHORT_CODE_PATTERN = re.compile(r"^[0-9a-f]{%d}$" % SHORT_CODE_LENGTH)
SCORE_FOLDER_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def short_code(score_id):
    return score_id[:SHORT_CODE_LENGTH]


def _record_path(code, root):
    return os.path.join(root, "links", f"{code}.json")


def write_record(score, options, root=MEDIA_ROOT):
    """Remember what /s/<code> opens: written beside the options each time they are saved."""
    from talkingscoresapp.models import write_text_file_atomic

    record = {
        "id": score.id,
        "filename": score.filename,
        "source": score.source(),
        "options": options,
    }
    write_text_file_atomic(_record_path(short_code(score.id), root), json.dumps(record))


def read_record(code, root=MEDIA_ROOT):
    if not SHORT_CODE_PATTERN.match(code):
        return None
    try:
        with open(_record_path(code, root), "r", encoding="utf-8") as record_file:
            record = json.load(record_file)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    if not isinstance(record.get("id"), str) or not SCORE_FOLDER_PATTERN.match(record["id"]):
        return None
    if not record["id"].startswith(code) or not isinstance(record.get("filename"), str):
        return None
    return record


def stored_score(code, root=MEDIA_ROOT):
    """(id, filename) of a stored score whose id starts with code, or None.

    Used when there is no record: a score opened before records were written,
    or one whose options were never saved.
    """
    if not SHORT_CODE_PATTERN.match(code) or not os.path.isdir(root):
        return None
    for name in sorted(os.listdir(root)):
        if not (SCORE_FOLDER_PATTERN.match(name) and name.startswith(code)):
            continue
        folder = os.path.join(root, name)
        scores = sorted(entry for entry in os.listdir(folder) if entry.endswith(".musicxml"))
        if scores:
            return name, scores[0]
    return None


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_TITLE_NAME_LENGTH = 48
MAX_NAME_ATTEMPTS = 50
# Names a short domain pointed at this site could not tell from its own pages.
RESERVED_NAMES = frozenset({
    "about", "admin", "change-log", "contact-us", "download", "find-a-score", "help", "library",
    "media", "midi-player", "midis", "options", "privacy-policy", "process", "robots-txt", "s",
    "score", "score-options", "share", "sitemap-xml", "static", "untitled-work",
})


def _names_dir(root):
    return os.path.join(root, "links", "names")


def _name_path(name, root):
    return os.path.join(_names_dir(root), name)


def _name_of_code_path(code, root):
    return os.path.join(root, "links", f"{code}.name")


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as text_file:
            return text_file.read().strip()
    except OSError:
        return None


def title_name(title):
    """The title as lower-case words joined by hyphens, cut at a word to fit, or "" when nothing usable is left."""
    name = slugify(title or "")
    while len(name) > MAX_TITLE_NAME_LENGTH and "-" in name:
        name = name.rsplit("-", 1)[0]
    name = name[:MAX_TITLE_NAME_LENGTH].strip("-")
    if not name or name in RESERVED_NAMES or SHORT_CODE_PATTERN.match(name):
        return ""
    return name


def word_name():
    return "-".join(secrets.choice(words) for words in (
        share_words.TEMPOS_AND_MOODS, share_words.INSTRUMENTS, share_words.FORMS))


def _abandoned(code, root):
    """True when nothing can open the score a name points at: it was uploaded and is no longer stored."""
    record = read_record(code, root)
    if record and record.get("source"):
        return False
    return stored_score(code, root) is None


def _claim(name, code, root, reclaim_abandoned):
    """Point name at code unless it already points at another score. Returns whether name now opens code."""
    from talkingscoresapp.models import write_text_file_atomic

    os.makedirs(_names_dir(root), exist_ok=True)
    path = _name_path(name, root)
    try:
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
    except FileExistsError:
        holder = _read_text(path)
        if holder == code:
            return True
        if not (reclaim_abandoned and holder and _abandoned(holder, root)):
            return False
        write_text_file_atomic(path, code)
        return True
    with os.fdopen(fd, "w", encoding="utf-8") as name_file:
        name_file.write(code)
    return True


def share_name(score, title, root=MEDIA_ROOT):
    """The name in this score's short link, chosen once and kept.

    A score that cannot be named, because every name tried was taken, keeps its
    code as its name.
    """
    from talkingscoresapp.models import write_text_file_atomic

    code = short_code(score.id)
    chosen = _read_text(_name_of_code_path(code, root))
    if chosen and resolve(chosen, root) == code:
        return chosen

    base = title_name(title) if score.source() else ""
    if base:
        candidates = [base] + [f"{base}-{number}" for number in range(2, MAX_NAME_ATTEMPTS + 1)]
    else:
        candidates = (word_name() for _ in range(MAX_NAME_ATTEMPTS))
    for name in candidates:
        if _claim(name, code, root, reclaim_abandoned=not base):
            write_text_file_atomic(_name_of_code_path(code, root), name)
            return name
    return code


def share_path(score, title, root=MEDIA_ROOT):
    return f"/s/{share_name(score, title, root)}"


def resolve(name, root=MEDIA_ROOT):
    """The code a link name opens, ignoring case, or None for a name no score has."""
    name = (name or "").lower()
    if NAME_PATTERN.match(name) and len(name) <= 2 * MAX_TITLE_NAME_LENGTH:
        holder = _read_text(_name_path(name, root))
        if holder and SHORT_CODE_PATTERN.match(holder):
            return holder
    if SHORT_CODE_PATTERN.match(name):
        return name
    return None
