#!/bin/bash
# File writes are reserved for subagents. The orchestrator session plans and
# delegates; a hook input without agent_id is the orchestrator itself.
input=$(cat)

if [ -z "$(jq -r '.agent_id // empty' <<<"$input")" ]; then
  echo "Writes are reserved for subagents. Delegate this edit to the implementer agent." >&2
  exit 2
fi

exit 0
