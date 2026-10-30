"""Every score the site can open without the reader supplying a file.

Two catalogues share one search: the scores music21 installs alongside itself
(talkingscoresapp/data/library.json, rebuilt by scripts/build_library_index.py),
which open from disk, and OpenScore's songs and string quartets
(talkingscoresapp/data/openscore.json), which are fetched from GitHub when
opened. Each entry has an id that stays the same across rebuilds, so a link to
/library/<id> keeps working.
"""

import json
import os
from functools import lru_cache

from music21 import common

from talkingscores.settings import BASE_DIR
from talkingscoresapp import openscore

BUILT_IN_INDEX_PATH = os.path.join(BASE_DIR, "talkingscoresapp", "data", "library.json")
OPENSCORE_ID_PREFIX = "openscore-"

# One of each kind of score, short enough to read in a minute, each named by
# what it shows. Ids missing from the index are dropped rather than shown broken.
EXAMPLES = (
    ("leadsheet-fosterbrownhair", "a song with chord symbols"),
    ("bach-bwv846", "a Bach piano prelude"),
    ("bach-bwv269", "a Bach chorale in four parts"),
)


@lru_cache(maxsize=1)
def _built_in():
    try:
        with open(BUILT_IN_INDEX_PATH, encoding="utf-8") as index_file:
            entries = json.load(index_file)
    except (OSError, json.JSONDecodeError):
        return []
    return [dict(entry, source="built-in") for entry in entries]


def _openscore_id(entry):
    return OPENSCORE_ID_PREFIX + os.path.splitext(entry["url"].rsplit("/", 1)[-1])[0].lower()


# OpenScore's Lieder are songs, so they share a collection with the songs from music21.
OPENSCORE_COLLECTIONS = {"Lieder": "Songs"}


@lru_cache(maxsize=1)
def _openscore():
    return [
        dict(entry, id=_openscore_id(entry), source="openscore",
             collection=OPENSCORE_COLLECTIONS.get(entry["collection"], entry["collection"]))
        for entry in openscore._entries()
    ]


@lru_cache(maxsize=1)
def _by_id():
    return {entry["id"]: entry for entry in _built_in() + _openscore()}


@lru_cache(maxsize=1)
def _searchable():
    return [
        (entry, openscore._fold(f"{entry['composer']} {entry.get('also', '')} {entry['title']} {entry['set']} {entry['collection']}"))
        for entry in _built_in() + _openscore()
    ]


def get(entry_id):
    return _by_id().get(entry_id)


def search(query):
    """Every entry matching every word in query, across both catalogues, case- and accent-insensitively."""
    words = [openscore._fold(word) for word in query.split() if word]
    if not words:
        return []
    return [entry for entry, text in _searchable() if all(word in text for word in words)]


def suggestions():
    """The examples, then OpenScore's suggested songs: somewhere to start before a search."""
    by_url = {entry["url"]: entry for entry in _openscore()}
    return examples() + [by_url[url] for url in openscore.SUGGESTED_URLS if url in by_url]


def examples():
    return [dict(get(entry_id), label=label) for entry_id, label in EXAMPLES if get(entry_id)]


def collections():
    """(collection name, number of scores) for each collection, in the order the index lists them."""
    counts = {}
    for entry in _built_in() + _openscore():
        counts[entry["collection"]] = counts.get(entry["collection"], 0) + 1
    return list(counts.items())


def in_collection(name):
    return [entry for entry in _built_in() + _openscore() if entry["collection"] == name]


def size():
    return len(_built_in()) + len(_openscore())


def built_in_bytes(entry):
    """The file of a built-in entry, read from music21's corpus folder.

    The path comes from the index, never from a request, and is still checked
    to stay inside that folder.
    """
    root = os.path.realpath(str(common.getCorpusFilePath()))
    path = os.path.realpath(os.path.join(root, entry["path"]))
    if os.path.commonpath([root, path]) != root:
        raise FileNotFoundError(entry["path"])
    with open(path, "rb") as score_file:
        return score_file.read()
