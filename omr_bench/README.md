# Score-reader test bench

Compares programs that read sheet music from an image (optical music
recognition) on the same pages, and scores each against a known answer. It
decides which reader the site uses for uploaded PDFs and photos, and is the
yardstick for any reader we train ourselves.

The bench is separate from the site: it has its own Python environment
(`requirements.txt`), because the scoring tool needs a newer music21 than the
site uses. Nothing in it is imported by the site or its tests.

## Readers compared

| Reader | What it is | How it is given a page |
| --- | --- | --- |
| Audiveris | Open-source, Java, rule-based with trained symbol classifiers | The PDF of clean pages, the image of photos |
| homr | Open-source, Python, segmentation plus a transformer per staff | The image |
| Transcoda | Research model (2026), 59M parameters, whole page to `**kern` | The image |
| LEGATO | Research model (2025), about 940M parameters, whole page to ABC | The image |
| Flat | Paid web service, 1 credit a page | The image; needs `FLAT_TOKEN` |

Each is described in `engines.toml` (copied from `engines.example.toml`).
Adding a reader is a new section there: the command to run, and where its
answer ends up.

## Test sets

- **Ours** (`sets/ours`): 20 pages built from the corpus bundled with music21,
  the opening bars of each score drawn by Verovio onto one A4 page. Six piano
  pieces, three songs, a chorale, three string quartets, three small
  ensembles and four single-line tunes. Built by `bench build`. Phone photos
  of the same pages go in `sets/ours/photos/<page id>.jpg` and are scored
  against the same answers: print `sets/ours/print/all-pages.pdf`,
  photograph each page, and name each photo after its page.
- **Sheet Music Benchmark** (`sets/smb`): 685 real scanned pages with
  answers, from the Universidad de Alicante. Gated and licensed CC BY-NC 4.0:
  request access at https://huggingface.co/datasets/PRAIG/SMB and sign in
  with `hf auth login` before `bench fetch-smb`.

Generated sets and reader output stay out of git (`.gitignore`).

## Scores

For every page, `bench score` records:

- **Error, all**: OMR-NED from [musicdiff](https://pypi.org/project/musicdiff/),
  the measure the Sheet Music Benchmark uses. Edits needed to turn the
  reader's score into the answer, divided by the symbols in both. 0 is
  perfect, 1 is nothing right; a page the reader failed on counts as 1.
- **Error, notes**: the same, counting only notes and rests.
- **Dynamics, articulations, lyrics**: how many of the answer's markings the
  reader found in the same bar. These are what a talking score reads out
  besides the notes.
- **Seconds a page**.

Results go to `runs/<set>/scores.csv` (one row per reader and page) and
`runs/<set>/summary.md` (tables by kind of page and by texture).

## Running it

On the DGX Spark, `spark_bench.sh` installs everything in `~/omr` and reads
one page with each reader to prove it works; `spark_bench.sh run` then reads
every page and writes the scores.

By hand, in the bench environment:

```
python -m omr_bench.bench build
python -m omr_bench.bench run --engine homr audiveris
python -m omr_bench.bench score
```

`run` skips pages a reader has already read; `--force` reads them again.

Checks for the bench itself:

```
python -m unittest discover -s omr_bench/checks -p "*_test.py" -t .
```
