#!/usr/bin/env python3
"""PreToolUse hook: route this repo's test and check commands through the filter.

Rewrites a matching Bash command so its output is piped to
filter_test_output.py, returning only failures and a few lines of context.
`set -o pipefail` keeps the real exit status, and an already-piped command is
left alone so the rewrite cannot stack.
"""

import json
import re
import sys

FILTER = ".claude/hooks/filter_test_output.py"

# The commands this repo actually runs: the Django test runner and system checks.
TARGET = re.compile(r"\bmanage\.py\s+(test|check)\b")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if not TARGET.search(command) or FILTER in command:
        return 0

    rewritten = f"set -o pipefail; {{ {command} ; }} 2>&1 | python3 {FILTER}"
    json.dump(
        {
            "hookSpecificOutput": {"hookEventName": "PreToolUse"},
            "updatedInput": {"command": rewritten},
            "systemMessage": "Output filtered to failures only.",
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
