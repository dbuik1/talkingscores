#!/usr/bin/env python3
"""Collapse Django test/check output down to failures plus a little context.

Reads the full run on stdin and writes the short form to stdout. A passing run
is reduced to its summary; a failing run keeps every failure block whole, since
a truncated traceback costs another full run to recover.
"""

import re
import sys

# Lines that open a unittest failure block and the rule that closes it.
BLOCK_START = re.compile(r"^(=+|FAIL:|ERROR:)")
BLOCK_END = re.compile(r"^-{20,}\s*$")

# Always-interesting lines outside failure blocks.
KEEP = re.compile(
    r"^(Ran \d+ test|OK\b|FAILED\b|SystemCheckError|System check identified [1-9]"
    r"|CommandError|Traceback \(most recent call last\)"
    r"|\S*(Error|Exception|Warning): )"
)

CONTEXT_LINES = 3


def main() -> int:
    lines = sys.stdin.read().splitlines()

    kept = []
    in_block = False
    seen_dashes = False
    context_budget = 0

    for line in lines:
        if BLOCK_START.match(line):
            in_block = True
            seen_dashes = False
            kept.append(line)
            continue

        if in_block:
            kept.append(line)
            if BLOCK_END.match(line):
                # The dashed rule appears under the header and again at the end.
                if seen_dashes:
                    in_block = False
                    context_budget = CONTEXT_LINES
                seen_dashes = True
            continue

        if KEEP.match(line.strip()) or KEEP.match(line):
            kept.append(line)
            context_budget = CONTEXT_LINES
        elif context_budget and line.strip():
            kept.append(line)
            context_budget -= 1

    if not kept:
        # Nothing matched: fall back to the tail so the run is never silent.
        kept = [l for l in lines if l.strip()][-CONTEXT_LINES:]

    hidden = len(lines) - len(kept)
    for line in kept:
        print(line)
    if hidden > 0:
        print(f"[filtered: {hidden} more line(s) of passing output hidden]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
