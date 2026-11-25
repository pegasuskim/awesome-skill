#!/usr/bin/env bash
#
# Sets up Ghostty on macOS.
#
#   Brewfile                   Ghostty and the two fonts the config names,
#                              installed through `brew bundle`
#   files/config.ghostty       -> ~/Library/Application Support/com.mitchellh.ghostty/config.ghostty
#
# The config includes ~/.config/ghostty/herdr-keys.conf only when it exists,
# so this works alone. ../herdr/install.sh is what puts that file there.
#
# Idempotent -- re-running changes nothing further.
#
# Usage:
#   install.sh             install dependencies and config
#   install.sh --no-deps   config only; skip brew

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GHOSTTY_XDG_DIR="$HOME/.config/ghostty"
GHOSTTY_APP_DIR="$HOME/Library/Application Support/com.mitchellh.ghostty"

usage() {
    cat <<'USAGE'
Usage:
  install.sh             install dependencies and config
  install.sh --no-deps   config only; skip brew
USAGE
}

# shellcheck source=../lib.sh
. "$SRC/../lib.sh"
parse_args "$@"

[ "$(uname -s)" = "Darwin" ] || { echo "error: macOS only" >&2; exit 1; }

if [ "$deps" -eq 1 ]; then brew_bundle "$SRC/Brewfile"; fi

echo "ghostty"
install_file "$SRC/files/config.ghostty" "$GHOSTTY_APP_DIR/config.ghostty"

# Ghostty loads every one of these alongside config.ghostty, so any that exist
# can still change what the installed config sets.
for other in "$GHOSTTY_XDG_DIR/config" "$GHOSTTY_XDG_DIR/config.ghostty" "$GHOSTTY_APP_DIR/config"; do
    if [ -f "$other" ]; then
        echo "  note: $(short "$other") is also loaded by Ghostty and may override this config"
    fi
done

echo
if [ "$changed" -eq 1 ]; then
    echo "Done. Restart Ghostty to pick up the changes."
else
    echo "Nothing to do -- already installed."
fi
