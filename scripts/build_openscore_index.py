"""Build talkingscoresapp/data/openscore.json from local OpenScore clones.

OpenScore (https://musescore.com/openscore) publishes CC0 sheet music on
GitHub, with a ready-made compressed MusicXML (.mxl) file beside each score.
This script walks two of its repositories and writes one compact JSON file
listing every .mxl file, for the "Find a score" page to search.

Usage:
    git clone --filter=blob:none https://github.com/OpenScore/Lieder.git
    git clone --filter=blob:none --no-checkout https://github.com/OpenScore/StringQuartets.git
    python3 scripts/build_openscore_index.py --lieder Lieder --string-quartets StringQuartets

Each clone is read one of two ways:
  - a normal checkout: files are read straight off disk;
  - a checkout skipped with --no-checkout (as StringQuartets, whose 196
    scores would otherwise fetch a checked-out working tree for nothing):
    file lists and metadata come from `git ls-tree` and `git show` instead,
    against that clone's default branch.
Either way, the .mxl files themselves are never downloaded here; the JSON
records each one's raw.githubusercontent.com URL for the site to fetch later.

Re-run this script whenever OpenScore adds scores, and commit the result.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from urllib.parse import quote, unquote

import yaml

GITHUB_OWNER = "OpenScore"
LIEDER_REPO = "Lieder"
STRING_QUARTETS_REPO = "StringQuartets"

SET_PREFIX_PATTERN = re.compile(r"^\d+_")


def run_git(repo_root, *args):
    result = subprocess.run(
        ["git", "-C", repo_root, *args],
        check=True, capture_output=True, text=True,
    )
    return result.stdout


def default_branch(repo_root):
    ref = run_git(repo_root, "symbolic-ref", "--short", "HEAD").strip()
    return ref or "main"


def has_working_tree(repo_root, relative_path):
    return os.path.isdir(os.path.join(repo_root, relative_path))


def read_repo_file(repo_root, branch, relative_path):
    """The text of a file in the clone, from disk if checked out, else from git show."""
    disk_path = os.path.join(repo_root, relative_path)
    if os.path.isfile(disk_path):
        with open(disk_path, encoding="utf-8") as source_file:
            return source_file.read()
    return run_git(repo_root, "show", f"{branch}:{relative_path}")


def list_mxl_paths(repo_root, branch, scores_dir):
    """Every .mxl path under scores_dir, relative to scores_dir."""
    if has_working_tree(repo_root, scores_dir):
        paths = []
        for root, _dirs, files in os.walk(os.path.join(repo_root, scores_dir)):
            for name in files:
                if name.endswith(".mxl"):
                    full = os.path.join(root, name)
                    paths.append(os.path.relpath(full, os.path.join(repo_root, scores_dir)))
        return sorted(paths)
    # -z keeps paths with accented letters unquoted, so they match the prefix test.
    tracked = run_git(repo_root, "ls-tree", "-r", "-z", "--name-only", branch).split("\0")
    prefix = scores_dir + "/"
    return sorted(
        path[len(prefix):] for path in tracked
        if path.startswith(prefix) and path.endswith(".mxl")
    )


def load_yaml_map(repo_root, branch, relative_path):
    """id -> record, from a StrictYAML data file keyed by numeric id."""
    text = read_repo_file(repo_root, branch, relative_path)
    data = yaml.safe_load(text) or {}
    return {str(key): value for key, value in data.items()}


def display_title(folder_name):
    stripped = SET_PREFIX_PATTERN.sub("", folder_name)
    return stripped.replace("_", " ")


# composers.yaml gives some composers a name readers would not search for:
# Clara Schumann's songs are listed there under her maiden name.
DISPLAY_NAMES = {
    "Schumann,_Clara": "Clara Schumann",
}


def folder_name_as_written(folder_name):
    last, _, first = folder_name.replace("_", " ").partition(", ")
    return f"{first} {last}".strip() if first else last


def composer_display_name(folder_name, composers_by_path):
    if folder_name in DISPLAY_NAMES:
        return DISPLAY_NAMES[folder_name]
    record = composers_by_path.get(folder_name)
    if record and record.get("name"):
        return record["name"]
    return folder_name_as_written(folder_name)


def also_known_as(folder_name, composer):
    """The folder's form of the name, when it differs, so either form finds the score."""
    written = folder_name_as_written(folder_name)
    return written if written != composer else ""


def raw_github_url(repo, branch, path_segments):
    encoded = "/".join(quote(segment, safe="") for segment in path_segments)
    return f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{repo}/{branch}/{encoded}"


def sort_key_prefix(folder_name):
    match = re.match(r"^(\d+)_", folder_name)
    return int(match.group(1)) if match else 0


def build_lieder_entries(repo_root):
    branch = default_branch(repo_root)
    composers_by_path = {
        record["path"]: record
        for record in load_yaml_map(repo_root, branch, "data/composers.yaml").values()
        if record.get("path")
    }
    sets_by_path = {
        record["path"]: record
        for record in load_yaml_map(repo_root, branch, "data/sets.yaml").values()
        if record.get("path")
    }

    entries = []
    for mxl_path in list_mxl_paths(repo_root, branch, "scores"):
        parts = mxl_path.split("/")
        if len(parts) != 4:
            continue
        composer_dir, set_dir, song_dir, _filename = parts

        composer = composer_display_name(composer_dir, composers_by_path)

        if set_dir == "_":
            set_name = ""
        else:
            set_record = sets_by_path.get(f"{composer_dir}/{set_dir}")
            set_name = set_record["name"] if set_record and set_record.get("name") else set_dir.replace("_", " ")

        entries.append({
            "collection": "Lieder",
            "composer": composer,
            "also": also_known_as(composer_dir, composer),
            "title": display_title(song_dir),
            "set": set_name,
            "order": sort_key_prefix(song_dir),
            "url": raw_github_url(LIEDER_REPO, branch, ["scores", *parts]),
        })
    return entries


def build_string_quartet_entries(repo_root):
    branch = default_branch(repo_root)
    composers_by_path = {
        record["path"]: record
        for record in load_yaml_map(repo_root, branch, "data/composers.yaml").values()
        if record.get("path")
    }
    scores_by_path = {
        record["path"]: record
        for record in load_yaml_map(repo_root, branch, "data/scores.yaml").values()
        if record.get("path")
    }

    entries = []
    for mxl_path in list_mxl_paths(repo_root, branch, "scores"):
        parts = mxl_path.split("/")
        if len(parts) != 3:
            continue
        composer_dir, work_dir, _filename = parts

        composer = composer_display_name(composer_dir, composers_by_path)
        score_record = scores_by_path.get(f"{composer_dir}/{work_dir}")
        title = score_record["name"] if score_record and score_record.get("name") else work_dir.replace("_", " ")

        entries.append({
            "collection": "String quartets",
            "composer": composer,
            "also": also_known_as(composer_dir, composer),
            "title": title,
            "set": "",
            "order": 0,
            "url": raw_github_url(STRING_QUARTETS_REPO, branch, ["scores", *parts]),
        })
    return entries


def composer_surname(entry):
    folder = entry["url"].split("/scores/", 1)[1].split("/", 1)[0]
    return unquote(folder).split(",_", 1)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lieder", required=True, help="path to a local clone of OpenScore/Lieder")
    parser.add_argument("--string-quartets", required=True, help="path to a local clone of OpenScore/StringQuartets")
    parser.add_argument(
        "--out", default=os.path.join("talkingscoresapp", "data", "openscore.json"),
        help="where to write the index (default: talkingscoresapp/data/openscore.json)",
    )
    args = parser.parse_args()

    entries = build_lieder_entries(args.lieder) + build_string_quartet_entries(args.string_quartets)
    entries.sort(key=lambda entry: (composer_surname(entry), entry["set"], entry["order"], entry["title"]))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as out_file:
        json.dump(entries, out_file, ensure_ascii=False, separators=(",", ":"))

    size_bytes = os.path.getsize(args.out)
    lieder_count = sum(1 for entry in entries if entry["collection"] == "Lieder")
    quartet_count = sum(1 for entry in entries if entry["collection"] == "String quartets")
    print(f"Wrote {args.out}: {len(entries)} scores ({lieder_count} Lieder, {quartet_count} string quartets), {size_bytes} bytes")


if __name__ == "__main__":
    sys.exit(main())
