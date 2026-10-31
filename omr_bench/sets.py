"""Read a test set: the pages each reader is given and the answer for each page.

A set is a folder with manifest.csv (written by build_set.py or fetch_smb.py).
Phone photos in photos/<id>.jpg are added as extra items of kind "photo" that
share the answer of the clean page with the same id.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".heic")


@dataclass(frozen=True)
class Item:
    key: str        # unique within the set, used for output file names
    piece: str      # the manifest id; photos share it with their clean page
    kind: str       # clean, photo or scan
    texture: str
    image: Path
    pdf: Path | None
    truth: Path


def load_items(set_dir):
    set_dir = Path(set_dir)
    items = []
    with open(set_dir / "manifest.csv", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            truth = set_dir / row["truth"]
            pdf = set_dir / row["pdf"] if row.get("pdf") else None
            items.append(Item(row["id"], row["id"], row["kind"], row["texture"],
                              set_dir / row["image"], pdf, truth))
            for photo in sorted((set_dir / "photos").glob(f"{row['id']}.*")):
                if photo.suffix.lower() in PHOTO_SUFFIXES:
                    items.append(Item(f"{row['id']}.photo", row["id"], "photo",
                                      row["texture"], photo, None, truth))
                    break
    return items
