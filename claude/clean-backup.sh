#!/usr/bin/env bash
#
# Removes the timestamped backups install.sh leaves in ~/.claude.
#
# install.sh copies a file to <name>.bak.<timestamp> before rewriting it, so one
# accumulates per run that changed something. Only CLAUDE.md and settings.json
# are ever backed up, both at the top of ~/.claude, so that is all this looks at.
#
# The newest backup of each file is kept by default -- that is the one an undo
# would reach for. Understand what --all discards before reaching for it:
# install.sh replaces plain settings keys outright and records nothing about
# what they held before, so these backups are the only surviving record of the
# values it displaced.
#
# Usage:
#   clean-backup.sh             keep the newest backup of each file
#   clean-backup.sh --all       remove every backup
#   clean-backup.sh --dry-run   report what would go; remove nothing
#
# The two options combine.
#
# Paths are fixed to ~/.claude so they stay in step with install.sh.
# CLAUDE_CONFIG_DIR is not honoured.

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"

remove_all=0
dry_run=0

usage() {
    cat <<'USAGE'
Usage:
  clean-backup.sh             keep the newest backup of each file
  clean-backup.sh --all       remove every backup
  clean-backup.sh --dry-run   report what would go; remove nothing

The two options combine.
USAGE
}

if [ "$#" -gt 0 ]; then
    for arg in "$@"; do
        case "$arg" in
            --all)     remove_all=1 ;;
            --dry-run) dry_run=1 ;;
            -h|--help) usage; exit 0 ;;
            *) echo "error: unknown option: $arg" >&2; usage >&2; exit 1 ;;
        esac
    done
fi

[ -d "$CLAUDE_DIR" ] || { echo "Nothing to do -- $CLAUDE_DIR does not exist."; exit 0; }

# Timestamps are fixed-width %Y%m%d%H%M%S, so a lexical sort is chronological.
bases="$(find "$CLAUDE_DIR" -maxdepth 1 -type f -name '*.bak.[0-9]*' \
         | sed 's/\.bak\.[0-9][0-9]*$//' | sort -u)"

if [ -z "$bases" ]; then
    echo "Nothing to do -- no backups in $CLAUDE_DIR."
    exit 0
fi

removed=0
kept=0

while IFS= read -r base; do
    [ -n "$base" ] || continue
    name="$(basename "$base")"
    echo "$name"

    group="$(find "$CLAUDE_DIR" -maxdepth 1 -type f -name "$name.bak.[0-9]*" | sort)"

    if [ "$remove_all" -eq 1 ]; then
        doomed="$group"
        survivor=""
    else
        doomed="$(printf '%s\n' "$group" | sed '$d')"
        survivor="$(printf '%s\n' "$group" | tail -n 1)"
    fi

    while IFS= read -r b; do
        [ -n "$b" ] || continue
        if [ "$dry_run" -eq 1 ]; then
            echo "  $(basename "$b"): would remove"
        else
            rm -f "$b"
            echo "  $(basename "$b"): removed"
        fi
        removed=$((removed + 1))
    done <<< "$doomed"

    if [ -n "$survivor" ]; then
        echo "  $(basename "$survivor"): kept (newest)"
        kept=$((kept + 1))
    fi
done <<< "$bases"

echo
if [ "$dry_run" -eq 1 ]; then
    echo "Dry run -- nothing was changed. $removed would be removed, $kept kept."
else
    echo "Done. $removed removed, $kept kept."
fi
