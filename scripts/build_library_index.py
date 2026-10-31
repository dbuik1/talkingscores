"""Build talkingscoresapp/data/library.json from the scores music21 installs.

music21 ships a corpus of public-domain scores inside the package, so these
open without a download. This script lists the MusicXML ones worth reading:
every Bach chorale, named from music21's own chorale tables, and a hand-picked
set of piano pieces, songs and chamber music whose stored titles are file
names or scanning errors, so each is named here instead.

Usage:
    python3 scripts/build_library_index.py           # write the index
    python3 scripts/build_library_index.py --check   # also open every score as a talking score

Re-run it after upgrading music21, and commit the result.
"""

import argparse
import json
import os
import re
import sys

from music21 import corpus
from music21.corpus import chorales

OUTPUT = os.path.join(os.path.dirname(__file__), "..", "talkingscoresapp", "data", "library.json")

# path in the corpus: (collection, composer, title, set)
CURATED = {
    "bach/bwv846.mxl": ("Piano", "Johann Sebastian Bach", "Prelude in C major, BWV 846", "The Well-Tempered Clavier, Book 1"),
    "joplin/maple_leaf_rag.mxl": ("Piano", "Scott Joplin", "Maple Leaf Rag", ""),
    "mozart/k545/movement1_exposition.mxl": ("Piano", "Wolfgang Amadeus Mozart", "Piano Sonata in C major, K. 545: first movement, opening", ""),
    "cpebach/h186.mxl": ("Piano", "Carl Philipp Emanuel Bach", "Sonata in A major, H. 186: Poco adagio", ""),
    "schumann_clara/polonaise_op1n1.mxl": ("Piano", "Clara Schumann", "Polonaise No. 1", "Four Polonaises, Op. 1"),
    "schumann_clara/polonaise_op1n2.mxl": ("Piano", "Clara Schumann", "Polonaise No. 2", "Four Polonaises, Op. 1"),
    "schumann_clara/polonaise_op1n3.mxl": ("Piano", "Clara Schumann", "Polonaise No. 3", "Four Polonaises, Op. 1"),
    "schumann_clara/polonaise_op1n4.mxl": ("Piano", "Clara Schumann", "Polonaise No. 4", "Four Polonaises, Op. 1"),
    "schoenberg/opus19/movement2.mxl": ("Piano", "Arnold Schoenberg", "No. 2", "Six Little Piano Pieces, Op. 19"),
    "schoenberg/opus19/movement6.mxl": ("Piano", "Arnold Schoenberg", "No. 6", "Six Little Piano Pieces, Op. 19"),
    "leadSheet/fosterBrownHair.mxl": ("Songs", "Stephen Foster", "Jeanie with the Light Brown Hair", "Melody and chord symbols"),
    "leadSheet/berlinAlexandersRagtime.mxl": ("Songs", "Irving Berlin", "Alexander's Ragtime Band", "Melody and chord symbols"),
    "schubert/Lindenbaum.xml": ("Songs", "Franz Schubert", "Der Lindenbaum", "Winterreise, D. 911"),
    "schumann_robert/opus48no2.mxl": ("Songs", "Robert Schumann", "Aus meinen Tränen sprießen", "Dichterliebe, Op. 48"),
    "beach/prayer_of_a_tired_child.musicxml": ("Songs", "Amy Beach", "Prayer of a Tired Child", "Op. 75"),
    "johnson_j_r/lift_every_voice.mxl": ("Songs", "J. Rosamond Johnson", "Lift Every Voice and Sing", ""),
    "liliuokalani/aloha_oe.mxl": ("Songs", "Liliʻuokalani", "Aloha ʻOe", ""),
    "handel/rinaldo/Lascia_chio_pianga.mxl": ("Songs", "George Frideric Handel", "Lascia ch'io pianga", "Rinaldo"),
    "verdi/laDonnaEMobile.mxl": ("Songs", "Giuseppe Verdi", "La donna è mobile", "Rigoletto"),
    "lusitano/allor_che_ignuda.mxl": ("Choral", "Vicente Lusitano", "Allor che ignuda", ""),
    "corelli/opus3no1/1grave.xml": ("Chamber music", "Arcangelo Corelli", "Trio Sonata, Op. 3 No. 1: Grave", ""),
    "weber/concertino_clarinet.mxl": ("Chamber music", "Carl Maria von Weber", "Concertino for Clarinet and Piano", ""),
    "schumann_clara/opus17/movement3.xml": ("Chamber music", "Clara Schumann", "Piano Trio in G minor, Op. 17: third movement", ""),
}

QUARTETS = {
    "beethoven/opus18no1/movement{}.mxl": ("Ludwig van Beethoven", "String Quartet in F major, Op. 18 No. 1", 4),
    "beethoven/opus59no1/movement{}.mxl": ("Ludwig van Beethoven", "String Quartet in F major, Op. 59 No. 1", 4),
    "beethoven/opus59no2/movement{}.mxl": ("Ludwig van Beethoven", "String Quartet in E minor, Op. 59 No. 2", 4),
    "beethoven/opus59no3/movement{}.mxl": ("Ludwig van Beethoven", "String Quartet in C major, Op. 59 No. 3", 4),
    "haydn/opus1no1/movement{}.mxl": ("Joseph Haydn", "String Quartet in B flat major, Op. 1 No. 1", 5),
    "haydn/opus74no1/movement{}.mxl": ("Joseph Haydn", "String Quartet in C major, Op. 74 No. 1", 4),
    "mozart/k80/movement{}.mxl": ("Wolfgang Amadeus Mozart", "String Quartet in G major, K. 80", 4),
    "mozart/k155/movement{}.mxl": ("Wolfgang Amadeus Mozart", "String Quartet in D major, K. 155", 3),
    "mozart/k156/movement{}.mxl": ("Wolfgang Amadeus Mozart", "String Quartet in G major, K. 156", 4),
    "mozart/k458/movement{}.mxl": ("Wolfgang Amadeus Mozart", "String Quartet in B flat major, K. 458", 4),
    "schumann_robert/opus41no1/movement{}.mxl": ("Robert Schumann", "String Quartet in A minor, Op. 41 No. 1", 5),
}

WHOLE_QUARTETS = {
    "beethoven/opus18no3.mxl": ("Ludwig van Beethoven", "String Quartet in D major, Op. 18 No. 3"),
    "beethoven/opus18no4.mxl": ("Ludwig van Beethoven", "String Quartet in C minor, Op. 18 No. 4"),
    "beethoven/opus18no5.mxl": ("Ludwig van Beethoven", "String Quartet in A major, Op. 18 No. 5"),
    "beethoven/opus74.mxl": ("Ludwig van Beethoven", "String Quartet in E flat major, Op. 74"),
    "beethoven/opus132.mxl": ("Ludwig van Beethoven", "String Quartet in A minor, Op. 132"),
    "beethoven/opus133.mxl": ("Ludwig van Beethoven", "Große Fuge, Op. 133"),
}

ORDINALS = ["first", "second", "third", "fourth", "fifth"]

CHORALE_PATTERN = re.compile(r"^bach/bwv(?P<bwv>\d+(?:\.\d+)?)(?P<variant>-[a-z0-9]+)?\.(?:mxl|xml)$")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def corpus_paths():
    """Every MusicXML path in the corpus, relative to its root, with forward slashes."""
    paths = []
    for path in corpus.corpora.CoreCorpus().getPaths():
        text = str(path).replace(os.sep, "/")
        if text.endswith((".mxl", ".xml", ".musicxml")) and "/corpus/" in text:
            paths.append(text.split("/corpus/", 1)[1])
    return sorted(paths)


def chorale_title(bwv):
    by_rk = chorales.ChoraleListRKBWV().byBWV
    by_number = chorales.ChoraleList().byBWV
    if bwv in by_rk:
        return by_rk[bwv]["title"]
    if bwv.isdigit() and int(bwv) in by_number:
        return by_number[int(bwv)]["title"]
    return None


def entry(path, collection, composer, title, set_name, order):
    return {
        "id": slug(os.path.splitext(path)[0]),
        "collection": collection,
        "composer": composer,
        "also": "",
        "title": title,
        "set": set_name,
        "order": order,
        "path": path,
    }


def build(paths):
    available = set(paths)
    entries = []

    for path, (collection, composer, title, set_name) in CURATED.items():
        if path in available:
            entries.append(entry(path, collection, composer, title, set_name, 0))

    for pattern, (composer, work, count) in QUARTETS.items():
        for number in range(1, count + 1):
            path = pattern.format(number)
            if path in available:
                entries.append(entry(path, "String quartets", composer, f"{work}: {ORDINALS[number - 1]} movement", work, number))

    for path, (composer, work) in WHOLE_QUARTETS.items():
        if path in available:
            entries.append(entry(path, "String quartets", composer, work, "", 0))

    for path in paths:
        match = CHORALE_PATTERN.match(path)
        if not match or path in CURATED:
            continue
        bwv = match.group("bwv")
        named = chorale_title(bwv)
        title = f"{named}, BWV {bwv}" if named else f"Chorale, BWV {bwv}"
        if match.group("variant"):
            title += f" (version {match.group('variant')[1:]})"
        entries.append(entry(path, "Bach chorales", "Johann Sebastian Bach", title, "Chorales", 0))

    ids = [item["id"] for item in entries]
    duplicates = {item for item in ids if ids.count(item) > 1}
    if duplicates:
        sys.exit(f"Two entries share an id: {sorted(duplicates)}")

    collection_order = ["Piano", "Songs", "Choral", "Chamber music", "String quartets", "Bach chorales"]
    entries.sort(key=lambda item: (collection_order.index(item["collection"]), item["composer"].split()[-1], item["set"], item["order"], item["title"]))
    return entries


def check(entries):
    """Open every entry the way the site does; a score that fails is dropped from the index."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "talkingscores.settings")
    os.environ.setdefault("DJANGO_DEBUG", "true")
    import django
    django.setup()
    from talkingscoreslib import Music21TalkingScore
    import tempfile
    import zipfile

    root = str(corpus.corpora.CoreCorpus().getPaths()[0]).replace(os.sep, "/").split("/corpus/", 1)[0] + "/corpus/"
    kept = []
    for item in entries:
        source = os.path.join(root, item["path"])
        with tempfile.TemporaryDirectory() as work:
            target = os.path.join(work, "score.musicxml")
            try:
                if source.endswith(".mxl"):
                    with zipfile.ZipFile(source) as archive:
                        names = [n for n in archive.namelist() if not n.startswith("META-INF/") and n.endswith((".xml", ".musicxml"))]
                        with open(target, "wb") as out:
                            out.write(archive.read(names[0]))
                else:
                    target = source
                Music21TalkingScore(target)
                kept.append(item)
            except Exception as exc:
                print(f"Dropped {item['path']}: {exc}", file=sys.stderr)
    return kept


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="open every score and drop those that fail")
    args = parser.parse_args()

    entries = build(corpus_paths())
    if args.check:
        entries = check(entries)
    with open(OUTPUT, "w", encoding="utf-8") as output:
        # One score per line, so a rebuild's diff shows which scores changed.
        output.write("[\n" + ",\n".join(json.dumps(item, ensure_ascii=False) for item in entries) + "\n]\n")
    print(f"Wrote {len(entries)} scores to {os.path.normpath(OUTPUT)}")


if __name__ == "__main__":
    main()
