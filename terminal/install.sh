#!/usr/bin/env bash
#
# Sets up Ghostty, then herdr inside it, by running both installers in turn.
# Each also works alone: see ghostty/install.sh and herdr/install.sh.
#
# Usage:
#   install.sh             install dependencies and config
#   install.sh --no-deps   config only; skip brew and the herdr integrations

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SRC/ghostty/install.sh" "$@"
echo
"$SRC/herdr/install.sh" "$@"
