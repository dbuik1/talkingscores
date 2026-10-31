"""Compare score readers on the same pages.

    python -m omr_bench.bench build                      # make our own 20-page set
    python -m omr_bench.bench fetch-smb                  # download the Sheet Music Benchmark
    python -m omr_bench.bench run --engine homr          # read every page with one reader
    python -m omr_bench.bench score                      # score every reader that has run

Outputs go under runs/<set>/<reader>/, one file per page plus log.jsonl.
Scores go to runs/<set>/scores.csv and runs/<set>/summary.md.
"""

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

DEFAULT_SET = "omr_bench/sets/ours"
DEFAULT_RUNS = "omr_bench/runs"
DEFAULT_ENGINES = "omr_bench/engines.toml"


def set_runs_dir(runs, set_dir):
    return Path(runs) / Path(set_dir).name


def read_log(log_path):
    entries = {}
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                entries[entry["key"]] = entry
    return entries


def command_run(args):
    from omr_bench.engines import load_engines, run
    from omr_bench.sets import load_items

    engines = load_engines(args.engines)
    names = list(engines) if args.engine == ["all"] else args.engine
    missing = [name for name in names if name not in engines]
    if missing:
        raise SystemExit(f"Not in {args.engines}: {', '.join(missing)}")
    items = [item for item in load_items(args.set) if not args.kind or item.kind in args.kind]
    if args.limit:
        items = items[: args.limit]
    for name in names:
        out_dir = set_runs_dir(args.runs, args.set) / name
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = out_dir / "log.jsonl"
        done = read_log(log_path)
        for item in items:
            if not args.force and done.get(item.key, {}).get("ok"):
                continue
            result = run(engines[name], item, out_dir)
            entry = {"key": item.key, "ok": result.ok, "seconds": round(result.seconds, 2),
                     "output": result.output.name if result.output else "", "error": result.error}
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
            state = "read" if result.ok else f"failed: {result.error}"
            print(f"{name} {item.key}: {state} ({result.seconds:.1f} s)")


def command_score(args):
    from omr_bench.score import MARKINGS, score_item
    from omr_bench.sets import load_items

    items = load_items(args.set)
    runs_dir = set_runs_dir(args.runs, args.set)
    engine_dirs = sorted(path for path in runs_dir.iterdir() if path.is_dir()) if runs_dir.exists() else []
    if not engine_dirs:
        raise SystemExit(f"No reader output in {runs_dir}. Run a reader first.")

    rows = []
    for engine_dir in engine_dirs:
        log = read_log(engine_dir / "log.jsonl")
        for item in items:
            entry = log.get(item.key)
            if entry is None:
                continue
            predicted = engine_dir / entry["output"] if entry.get("ok") and entry.get("output") else None
            row = {"engine": engine_dir.name, "page": item.key, "kind": item.kind,
                   "texture": item.texture, "read": bool(predicted), "seconds": entry["seconds"]}
            row.update(score_item(predicted, item.truth))
            rows.append(row)
            print(f"{engine_dir.name} {item.key}: OMR-NED {row['omr_ned']:.3f}")

    fields = ["engine", "page", "kind", "texture", "read", "seconds", "omr_ned", "omr_ned_notes"]
    fields += [f"{kind}_{side}" for kind in MARKINGS for side in ("expected", "found")]
    with open(runs_dir / "scores.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = summarise(rows)
    (runs_dir / "summary.md").write_text(summary, encoding="utf-8")
    print()
    print(summary)


def summarise(rows):
    from omr_bench.score import MARKINGS

    def table(group_key, heading):
        groups = defaultdict(list)
        for row in rows:
            groups[(row["engine"], row[group_key])].append(row)
        lines = [f"| Reader | {heading} | Pages | Read | Error, all | Error, notes | "
                 "Dynamics | Articulations | Lyrics | Seconds a page |",
                 "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for (engine, group), members in sorted(groups.items()):
            found = []
            for kind in MARKINGS:
                expected = sum(row[f"{kind}_expected"] for row in members)
                hits = sum(row[f"{kind}_found"] for row in members)
                found.append(f"{hits} of {expected}" if expected else "none")
            lines.append(
                f"| {engine} | {group} | {len(members)} | {sum(row['read'] for row in members)} | "
                f"{statistics.mean(row['omr_ned'] for row in members):.3f} | "
                f"{statistics.mean(row['omr_ned_notes'] for row in members):.3f} | "
                f"{' | '.join(found)} | {statistics.median(row['seconds'] for row in members):.1f} |")
        return "\n".join(lines)

    return ("Error is OMR-NED: 0 is perfect, 1 is nothing right. Pages a reader failed on count as 1.\n\n"
            "By kind of page\n\n" + table("kind", "Pages from") + "\n\n"
            "By texture\n\n" + table("texture", "Texture") + "\n")


def command_build(args):
    from omr_bench.build_set import build
    build(args.out)


def command_fetch_smb(args):
    from omr_bench.fetch_smb import fetch
    fetch(args.out, args.limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare score readers on the same pages.")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="make our own 20-page set from the music21 corpus")
    build.add_argument("--out", default=DEFAULT_SET)
    build.set_defaults(handler=command_build)

    smb = commands.add_parser("fetch-smb", help="download the Sheet Music Benchmark pages")
    smb.add_argument("--out", default="omr_bench/sets/smb")
    smb.add_argument("--limit", type=int, default=0, help="only the first N pages")
    smb.set_defaults(handler=command_fetch_smb)

    run = commands.add_parser("run", help="read every page with one or more readers")
    run.add_argument("--set", default=DEFAULT_SET)
    run.add_argument("--engines", default=DEFAULT_ENGINES)
    run.add_argument("--engine", nargs="+", required=True, help="reader names, or all")
    run.add_argument("--runs", default=DEFAULT_RUNS)
    run.add_argument("--kind", nargs="*", help="only these kinds of page: clean, photo, scan")
    run.add_argument("--limit", type=int, default=0, help="only the first N pages")
    run.add_argument("--force", action="store_true", help="read pages again that already worked")
    run.set_defaults(handler=command_run)

    score = commands.add_parser("score", help="score every reader that has run on a set")
    score.add_argument("--set", default=DEFAULT_SET)
    score.add_argument("--runs", default=DEFAULT_RUNS)
    score.set_defaults(handler=command_score)

    args = parser.parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
