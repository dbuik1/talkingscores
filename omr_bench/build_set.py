"""Build our own test set: one page per piece, with the answer as MusicXML.

For each piece in pieces.py this writes
    truth/<id>.musicxml   the bars on the page, as the answer each reader is scored against
    pages/<id>.png        the page at 300 dpi, the clean digital input
    pages/<id>.pdf        the same page as a PDF
and print/all-pages.pdf, every page in one file for printing and photographing.

Phone photos are added by hand as photos/<id>.jpg; sets.py picks them up.
"""

import argparse
import csv
import io
import sys
from pathlib import Path

import cairosvg
import verovio
from music21 import corpus, metadata, stream
from music21.musicxml.m21ToXml import GeneralObjectExporter
from pypdf import PdfWriter

from omr_bench.pieces import PIECES

# A4 in Verovio's units (tenths of a millimetre) and in pixels at 300 dpi.
PAGE_OPTIONS = {
    "pageWidth": 2100,
    "pageHeight": 2970,
    "scale": 40,
    "adjustPageHeight": False,
    "footer": "none",
    "breaks": "auto",
}
PNG_WIDTH = 2480
FONT_DIR = Path.home() / ".local" / "share" / "fonts"


def ensure_text_font():
    """Install Verovio's Leipzig font where Cairo can find it.

    Verovio draws flats in chord names and notes in tempo marks as text in
    Leipzig, embedded in the SVG as a web font. Cairo ignores web fonts, so
    without a system copy those symbols render as empty boxes.
    """
    target = FONT_DIR / "Leipzig.ttf"
    if target.exists():
        return
    import base64
    import re
    import subprocess
    from fontTools.ttLib import TTFont

    css = (Path(verovio.__file__).parent / "data" / "Leipzig.css").read_text()
    woff2 = base64.b64decode(re.search(r"base64,([^)]+)\)", css).group(1))
    font = TTFont(io.BytesIO(woff2))
    font.flavor = None
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    font.save(target)
    subprocess.run(["fc-cache", "-f", str(FONT_DIR)], check=False, capture_output=True)


def load_score(path):
    score = corpus.parse(path)
    if isinstance(score, stream.Opus):
        score = score.scores[0]
    return score


def bar_numbers(score):
    return [m.number for m in score.parts[0].getElementsByClass(stream.Measure)]


def excerpt(score, numbers, count, title):
    opening = score.measures(numbers[0], numbers[count - 1])
    opening.metadata = metadata.Metadata(title=title)
    return opening


def to_musicxml(score):
    return GeneralObjectExporter(score).parse().decode("utf-8")


def page_count(toolkit, xml):
    if not toolkit.loadData(xml):
        return 0
    return toolkit.getPageCount()


def fit_one_page(score, title, toolkit):
    """Return the longest opening excerpt that Verovio lays out on one page."""
    numbers = bar_numbers(score)
    best = None
    count = min(4, len(numbers))
    while count <= len(numbers):
        candidate = excerpt(score, numbers, count, title)
        xml = to_musicxml(candidate)
        if page_count(toolkit, xml) != 1:
            break
        best = (candidate, xml)
        count += 2
    if best is None:
        raise ValueError("the opening bars do not fit on one page")
    # Two bars at a time can stop one short of a full page.
    if count - 1 <= len(numbers):
        candidate = excerpt(score, numbers, count - 1, title)
        xml = to_musicxml(candidate)
        if page_count(toolkit, xml) == 1:
            best = (candidate, xml)
    toolkit.loadData(best[1])
    return best[0], toolkit.renderToSVG(1)


def build(out_dir):
    out_dir = Path(out_dir)
    for sub in ("truth", "pages", "print", "photos"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    ensure_text_font()
    toolkit = verovio.toolkit()
    toolkit.setOptions(PAGE_OPTIONS)

    rows = []
    printable = PdfWriter()
    for piece_id, path, texture, title in PIECES:
        try:
            page_bars, svg = fit_one_page(load_score(path), title, toolkit)
        except Exception as error:  # one bad corpus file must not stop the set
            print(f"skipped {piece_id}: {error}", file=sys.stderr)
            continue
        truth = out_dir / "truth" / f"{piece_id}.musicxml"
        truth.write_text(to_musicxml(page_bars), encoding="utf-8")
        png = out_dir / "pages" / f"{piece_id}.png"
        pdf = out_dir / "pages" / f"{piece_id}.pdf"
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(png),
                         output_width=PNG_WIDTH, background_color="white")
        cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(pdf))
        printable.append(str(pdf))
        bars = len(page_bars.parts[0].getElementsByClass(stream.Measure))
        rows.append({
            "id": piece_id,
            "kind": "clean",
            "texture": texture,
            "image": f"pages/{piece_id}.png",
            "pdf": f"pages/{piece_id}.pdf",
            "truth": f"truth/{piece_id}.musicxml",
            "bars": bars,
        })
        print(f"{piece_id}: {bars} bars")

    with open(out_dir / "print" / "all-pages.pdf", "wb") as handle:
        printable.write(handle)
    write_manifest(out_dir / "manifest.csv", rows)
    return rows


def write_manifest(path, rows):
    buffer = io.StringIO()
    fields = ["id", "kind", "texture", "image", "pdf", "truth", "bars"]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fields})
    Path(path).write_text(buffer.getvalue(), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="omr_bench/sets/ours")
    args = parser.parse_args(argv)
    rows = build(args.out)
    print(f"{len(rows)} pages written to {args.out}")


if __name__ == "__main__":
    main()
