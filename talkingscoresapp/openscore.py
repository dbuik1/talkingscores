"""Search over talkingscoresapp/data/openscore.json, the OpenScore catalogue.

Rebuild that file with scripts/build_openscore_index.py; this module only reads it.
"""

import json
import os
import unicodedata
from functools import lru_cache

from talkingscores.settings import BASE_DIR

INDEX_PATH = os.path.join(BASE_DIR, "talkingscoresapp", "data", "openscore.json")

# Picked for name recognition, not for musical importance: a well-known song from
# each of a few composers, and one quartet, so the empty-search page has somewhere
# to start. Each is matched by its URL against the built index, so an entry that
# a rebuild of the index no longer contains is dropped rather than shown broken.
SUGGESTED_URLS = (
    "https://raw.githubusercontent.com/OpenScore/Lieder/main/scores/Schubert%2C_Franz/Winterreise%2C_D.911/01_Gute_Nacht/lc5015378.mxl",
    "https://raw.githubusercontent.com/OpenScore/Lieder/main/scores/Schubert%2C_Franz/_/Der_Erlk%C3%B6nig%2C_D.328/lc29062370.mxl",
    "https://raw.githubusercontent.com/OpenScore/Lieder/main/scores/Schumann%2C_Robert/Dichterliebe%2C_Op.48/01_Im_wundersch%C3%B6nen_Monat_Mai/lc4976777.mxl",
    "https://raw.githubusercontent.com/OpenScore/Lieder/main/scores/Schumann%2C_Clara/Lieder%2C_Op.12/04_Liebst_du_um_Sch%C3%B6nheit/lc5000397.mxl",
    "https://raw.githubusercontent.com/OpenScore/Lieder/main/scores/Hensel%2C_Fanny/3_Lieder/1_Sehnsucht/lc6012947.mxl",
    "https://raw.githubusercontent.com/OpenScore/StringQuartets/main/scores/Beach%2C_Amy/String_Quartet%2C_Op._89/sq14387632.mxl",
)


@lru_cache(maxsize=1)
def _entries():
    try:
        with open(INDEX_PATH, encoding="utf-8") as index_file:
            return json.load(index_file)
    except (OSError, json.JSONDecodeError):
        return []


def _fold(text):
    """Lower-case with accents stripped, so "Erlkonig" matches "Erlkönig"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


@lru_cache(maxsize=1)
def _searchable_entries():
    """(entry, folded composer+title+set) for every entry, built once."""
    return [
        (entry, _fold(f"{entry['composer']} {entry.get('also', '')} {entry['title']} {entry['set']}"))
        for entry in _entries()
    ]


def search(query, limit):
    """(matches[:limit], total matching) for every word in query, matched case- and accent-insensitively."""
    words = [_fold(word) for word in query.split() if word]
    if not words:
        return [], 0

    matches = [
        entry for entry, text in _searchable_entries()
        if all(word in text for word in words)
    ]
    return matches[:limit], len(matches)


def suggestions():
    """A short, fixed list of well-known scores to show before the reader has searched."""
    by_url = {entry["url"]: entry for entry in _entries()}
    return [by_url[url] for url in SUGGESTED_URLS if url in by_url]
