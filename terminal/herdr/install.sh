#!/usr/bin/env bash
#
# Sets up herdr.
#
#   Brewfile                   herdr and jq, installed through `brew bundle`
#   files/herdr/*              -> ~/.config/herdr/
#   files/ghostty/herdr-keys.conf
#                              -> ~/.config/ghostty/herdr-keys.conf
#
# herdr-keys.conf is the herdr key bindings in Ghostty's format. The config
# that ../ghostty/install.sh writes picks it up when present, and Ghostty
# ignores it otherwise.
#
# The herdr integrations for claude and codex are installed too, each only when
# that tool's directory (~/.claude, ~/.codex) already exists.
#
# Idempotent -- re-running changes nothing further.
#
# Usage:
#   install.sh             install dependencies and config
#   install.sh --no-deps   config only; skip brew and the herdr integrations

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERDR_DIR="$HOME/.config/herdr"
GHOSTTY_XDG_DIR="$HOME/.config/ghostty"

usage() {
    cat <<'USAGE'
Usage:
  install.sh             install dependencies and config
  install.sh --no-deps   config only; skip brew and the herdr integrations
USAGE
}

# shellcheck source=../lib.sh
. "$SRC/../lib.sh"
parse_args "$@"

if [ "$deps" -eq 1 ]; then brew_bundle "$SRC/Brewfile"; fi

echo "herdr"
for f in "$SRC"/files/herdr/*; do
    install_file "$f" "$HERDR_DIR/$(basename "$f")"
done
install_file "$SRC/files/ghostty/herdr-keys.conf" "$GHOSTTY_XDG_DIR/herdr-keys.conf"

# --- herdr integrations ----------------------------------------------------
if [ "$deps" -eq 1 ]; then
    echo "herdr integrations"
    for agent in claude codex; do
        if [ -d "$HOME/.$agent" ]; then
            herdr integration install "$agent" >/dev/null
            echo "  $agent: $(herdr integration status 2>/dev/null | sed -n "s/^$agent: \([^(]*\).*/\1/p" | sed 's/ *$//')"
        else
            echo "  $agent: skipped (~/.$agent not found)"
        fi
    done
fi

echo
if [ "$changed" -eq 1 ]; then
    echo "Done. Restart Ghostty, and run 'herdr server reload-config' if a herdr server is already running."
else
    echo "Nothing to do -- already installed."
fi
