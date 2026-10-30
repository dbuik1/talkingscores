"""Short links to a talking score: /s/<code>.

A score's id is the SHA-256 of its file, so its first ten hex digits already
name it among any number of scores this site will hold; the code is that
prefix and needs no table to issue.

Each time options are saved, a small record is written under MEDIA_ROOT/links:
the score's id and file name, where the file came from and the options. The
score folders are cleaned up after a while, and the links folder is not, so a
link to a score that came from a web address or the library still opens: the
file is fetched again and the options put back. A link to an uploaded file
works only while that file is stored.
"""

import json
import os
import re

from talkingscores.settings import MEDIA_ROOT

SHORT_CODE_LENGTH = 10
SHORT_CODE_PATTERN = re.compile(r"^[0-9a-f]{%d}$" % SHORT_CODE_LENGTH)
SCORE_FOLDER_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def short_code(score_id):
    return score_id[:SHORT_CODE_LENGTH]


def short_path(score_id):
    return f"/s/{short_code(score_id)}"


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
