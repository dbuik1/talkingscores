#!/usr/bin/env python3
"""
check_user_copy.py

Heuristic scanner for text that should never reach a reader:
  - implementation rationale leaked into user-facing copy
  - marketing register in UI strings
  - negative-parallelism constructions ("not just X ... it's Y")
  - provenance comments ("as per CLAUDE.md section 6") and plan/phase IDs
    in code comments

Not a proof of correctness - a cheap net. Pair with the manual review pass
in the user-facing-copy-guard skill, not instead of it.

Usage:
    python3 check_user_copy.py path/to/strings.json src/**/*.ts
    python3 check_user_copy.py --comments src/**/*.py   # comment checks only
    python3 check_user_copy.py --copy strings.json      # copy checks only

Exits 0 if clean, 1 if anything looks suspicious (and prints the hits).
"""

import re
import sys
from pathlib import Path

# --- Copy checks: run over strings files / UI copy ---------------------------
COPY_PATTERNS = [
    (r"\bDEVNOTE\b", "dev marker left in user-facing file"),
    (r"@internal\b", "internal marker left in user-facing file"),
    (r"\bTODO\b", "TODO left in user-facing file"),
    (r"\bFIXME\b", "FIXME left in user-facing file"),
    (r"\bas (specified|instructed|per the spec|per spec)\b", "meta-reference to a spec/instruction"),
    (r"\bper the (note|spec|instructions?)\b", "meta-reference to a note/spec"),
    (r"\bnever blocked\b", "justificatory rationale phrasing"),
    (r"\bis never\b", "justificatory rationale phrasing"),
    (r"\bwe (chose|decided|skip|never|always)\b", "first-person developer rationale"),
    (r"\bbecause (legacy|the schema|of backwards|it predates)\b", "background/history rationale"),
    (r"\bnote that\b", "meta-commentary phrasing"),
    # Marketing register (word lists live here, not in the skill prompt)
    (r"\bseamless(ly)?\b", "marketing register"),
    (r"\beffortless(ly)?\b", "marketing register"),
    (r"\b(powerful|robust|delightful|intuitive)\b", "marketing register"),
    (r"\b(unlock|empower|elevate|supercharge|streamline|leverage|utilise|utilize)\b", "marketing register"),
    (r"\bdesign philosophy\b", "marketing register"),
    (r"\b(one-stop shop|hub for|portal for)\b", "marketing register"),
    # Negative parallelism: "not just X ... but/it's Y", "isn't a second thought, but Y"
    (r"(?i)\b(is |isn'?t |not )(just|merely|only|simply|a second thought)\b[^.\n]{0,60}(,|—|--|;)?\s*(but|it'?s)\b",
     "negative parallelism - assert the fact once"),
    (r"!{1}", "exclamation mark in UI copy"),
]

# --- Comment checks: run over source files -----------------------------------
COMMENT_PATTERNS = [
    (r"(?i)(as )?per (CLAUDE\.md|AGENTS\.md|the spec|the plan|section \d|[A-Z_]+\.md)", "provenance comment - state the constraint"),
    (r"(?i)\bas (discussed|requested|agreed|instructed)\b", "conversation provenance in comment"),
    (r"(?i)\b(per|from) (your|the user'?s) (note|feedback|request)\b", "conversation provenance in comment"),
    (r"Phase \d|Track [A-Z](-\d|\b)|Stage [A-Z]-\d|§ ?\d|Step \d §|Post-Phase-\d", "plan/phase ID in comment (plans change; comment becomes a lie)"),
    (r"(?i)\bfeedback item \d", "numbered feedback item in comment"),
]

COMMENT_LINE = re.compile(r"^\s*(#|//|/\*|\*|<!--|--)\s?(.*)")


def compiled(patterns):
    return [(re.compile(p, re.IGNORECASE), reason) for p, reason in patterns]


COPY_COMPILED = compiled(COPY_PATTERNS)
COMMENT_COMPILED = compiled(COMMENT_PATTERNS)


def scan_file(path: Path, mode: str):
    hits = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        print(f"warning: could not read {path}: {e}", file=sys.stderr)
        return hits

    for lineno, line in enumerate(text.splitlines(), start=1):
        m = COMMENT_LINE.match(line)
        if mode in ("all", "comments") and m:
            for pattern, reason in COMMENT_COMPILED:
                if pattern.search(m.group(2)):
                    hits.append((path, lineno, reason, line.strip()))
        if mode in ("all", "copy") and not m:
            for pattern, reason in COPY_COMPILED:
                if pattern.search(line):
                    hits.append((path, lineno, reason, line.strip()))
    return hits


def main(argv):
    args = argv[1:]
    mode = "all"
    if args and args[0] in ("--comments", "--copy"):
        mode = args.pop(0).lstrip("-")
    if not args:
        print(__doc__)
        return 1

    all_hits = []
    for arg in args:
        p = Path(arg)
        if p.is_file():
            all_hits.extend(scan_file(p, mode))
        else:
            print(f"warning: not a file, skipping: {arg}", file=sys.stderr)

    if not all_hits:
        print("No suspicious patterns found.")
        return 0

    print(f"Found {len(all_hits)} suspicious line(s):\n")
    for path, lineno, reason, line in all_hits:
        print(f"  {path}:{lineno}  [{reason}]")
        print(f"    {line}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
