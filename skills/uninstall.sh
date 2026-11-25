#!/usr/bin/env bash
#
# Removes the skill folders install.sh put into Claude Code and Codex.
#
# Only folders carrying install.sh's marker are removed, whether or not their
# skill still exists here. A skill someone installed by hand under the same
# name stays.
#
# Idempotent: re-running makes no further changes. Nothing in this directory
# is touched, so install.sh puts everything back.
#
# Usage:
#   uninstall.sh                       every skill this config installed
#   uninstall.sh <name>...             only these
#   uninstall.sh --dry-run [<name>...] report what would go; remove nothing

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

dry_run=0
names=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) dry_run=1 ;;
        -h|--help) sed -n 's/^#   //p' "${BASH_SOURCE[0]}" | sed -n '/^uninstall.sh/p'; exit 0 ;;
        -*) echo "error: unknown option: $arg" >&2; exit 1 ;;
        *) names="$names $arg" ;;
    esac
done

# shellcheck source=lib.sh
. "$SRC/lib.sh"

changed=0

for agent in $AGENTS; do
    label="${agent%%:*}"
    dir="${agent#*:}/skills"
    echo "$label"

    found=0
    for dest in "$dir"/*/; do
        dest="${dest%/}"
        [ -f "$dest/$MARKER" ] || continue
        name="$(basename "$dest")"
        # shellcheck disable=SC2086  # names is a space-separated list
        listed "$name" $names || continue
        found=1
        if [ "$dry_run" -eq 1 ]; then
            echo "  $name: would remove"
        else
            rm -rf "$dest"
            echo "  $name: removed"
        fi
        changed=1
    done
    [ "$found" -eq 1 ] || echo "  nothing installed by this config"
done

echo
if [ "$changed" -eq 0 ]; then
    echo "Nothing to do -- no skill of this config is installed."
elif [ "$dry_run" -eq 1 ]; then
    echo "Dry run -- nothing was changed."
else
    echo "Done. Start a new Claude Code or Codex session to pick up the changes."
fi
