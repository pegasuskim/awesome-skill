#!/usr/bin/env bash
# Injected into model context on every prompt (UserPromptSubmit hook).
set -euo pipefail

jq -n --arg ctx 'Before any causal claim, ranked hypothesis, or bug report: run the check that would confirm it, or label it unverified. A plausible guess is not a finding.' \
  '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $ctx}}'
