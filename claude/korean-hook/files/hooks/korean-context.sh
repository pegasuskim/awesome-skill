#!/usr/bin/env bash
# Injected into model context on every tool call (PreToolUse and PostToolUse hooks).
#
# Off unless the shell that launched Claude Code exports
#   HONG_CLAUDE_EXPERIMENT='{"korean-context":true}'
# Any other value, invalid JSON, or the variable being unset leaves it off.
set -euo pipefail

jq -ne 'env.HONG_CLAUDE_EXPERIMENT // "{}" | fromjson? | .["korean-context"] == true' >/dev/null 2>&1 || exit 0

event=$(jq -r '.hook_event_name // "PreToolUse"')

jq -n --arg event "$event" \
  --arg ctx '도구 호출 사이의 진행 메시지를 포함해, 사용자에게 보이는 모든 텍스트는 한국어로 작성하세요.' \
  '{hookSpecificOutput: {hookEventName: $event, additionalContext: $ctx}}'
