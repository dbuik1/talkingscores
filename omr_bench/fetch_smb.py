"""Download the Sheet Music Benchmark (PRAIG/SMB) as a test set.

685 real scanned pages with a full-page **kern answer each. The dataset is
gated: request access on its Hugging Face page, then run `hf auth login`
(or set HF_TOKEN) before fetching. Its licence is CC BY-NC 4.0, so pages
stay on the machine that runs the bench and never go into the repository.

The column holding the full-page answer is found by looking for **kern text,
since the dataset card does not name it.
"""

from pathlib import Path

from omr_bench.build_set import write_manifest

DATASET = "PRAIG/SMB"
TEXTURE_COLUMNS = ("texture", "category", "type")


def find_kern_column(example):
    """The longest text column whose value is **kern music."""
    candidates = [(len(value), name) for name, value in example.items()
                  if isinstance(value, str) and value.lstrip().startswith("**")]
    if not candidates:
        raise ValueError(f"No **kern column in {sorted(example)}")
    return max(candidates)[1]


def fetch(out_dir, limit=0):
    from datasets import load_dataset

    out_dir = Path(out_dir)
    (out_dir / "pages").mkdir(parents=True, exist_ok=True)
    (out_dir / "truth").mkdir(parents=True, exist_ok=True)
    rows = []
    kern_column = None
    for split_name, split in load_dataset(DATASET).items():
        for index, example in enumerate(split):
            if limit and len(rows) >= limit:
                break
            kern_column = kern_column or find_kern_column(example)
            page_id = f"{split_name}-{index:04d}"
            example["image"].convert("RGB").save(out_dir / "pages" / f"{page_id}.png")
            (out_dir / "truth" / f"{page_id}.krn").write_text(example[kern_column], encoding="utf-8")
            texture = next((str(example[name]) for name in TEXTURE_COLUMNS if name in example), "unknown")
            rows.append({"id": page_id, "kind": "scan", "texture": texture,
                         "image": f"pages/{page_id}.png", "truth": f"truth/{page_id}.krn"})
    write_manifest(out_dir / "manifest.csv", rows)
    print(f"{len(rows)} pages written to {out_dir}, answers taken from the '{kern_column}' column")
    return rows
