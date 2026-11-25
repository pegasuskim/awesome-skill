#!/usr/bin/env bash
#
# Installs every skill in this directory into Claude Code and Codex.
#
#   <name>/   -> ~/.claude/skills/<name>/
#             -> $CODEX_HOME/skills/<name>/   (default ~/.codex)
#
# A skill installs into both agents unless install.json names which ones:
#
#   { "readable-artifact": ["claude"] }
#
# An agent is skipped when its directory does not exist. Each installed folder
# is an exact copy of its source plus a marker file showing that this config
# installed it, so an update replaces the whole folder and a file dropped from
# the source goes with it.
#
# A folder of the same name without the marker is adopted when its content
# already equals the source, which is how a copy put there before this script
# existed gets taken over. Otherwise it belongs to someone else and is left
# alone.
#
# A marked folder is removed from an agent the skill no longer installs into.
# With no names, every skill is installed, and a marked folder whose skill no
# longer exists here is removed too. With names, only those skills are
# installed or removed, and nothing else is touched.
#
# Idempotent: re-running makes no further changes.
#
# Usage:
#   install.sh             every skill
#   install.sh <name>...   only these

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-}" in
    -h|--help)
        sed -n 's/^#   //p' "${BASH_SOURCE[0]}" | sed -n '/^install.sh/p'
        exit 0 ;;
    -*) echo "error: unknown option: $1" >&2; exit 1 ;;
esac

# shellcheck source=lib.sh
. "$SRC/lib.sh"

# What the marker records for every skill of this repo.
STAMP=local

skills="$(
    for d in "$SRC"/*/; do
        name="$(basename "$d")"
        [ -f "$d/SKILL.md" ] || { echo "error: $name/ has no SKILL.md" >&2; exit 1; }
        echo "$name"
    done
)"

command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 1; }

TARGETS="$SRC/install.json"
if [ -f "$TARGETS" ]; then
    jq -e 'type == "object" and all(.[]; type == "array" and length > 0
        and all(.[]; . == "claude" or . == "codex"))' "$TARGETS" >/dev/null 2>&1 \
        || { echo "error: install.json must map skill names to a non-empty list of \"claude\" and \"codex\"" >&2; exit 1; }
fi

targets_of() {  # name -> the agent labels it installs into
    if [ -f "$TARGETS" ]; then
        jq -r --arg n "$1" '(.[$n] // ["claude", "codex"]) | join(" ")' "$TARGETS"
    else
        echo "claude codex"
    fi
}

if [ -f "$TARGETS" ]; then
    for name in $(jq -r 'keys[]' "$TARGETS"); do
        printf '%s\n' "$skills" | awk -v n="$name" '$1 == n { f = 1 } END { exit !f }' \
            || echo "warning: install.json lists '$name', but skills/$name/ does not exist -- remove it from install.json" >&2
    done
fi

for want in "$@"; do
    printf '%s\n' "$skills" | awk -v n="$want" '$1 == n { f = 1 } END { exit !f }' \
        || { echo "error: no skill named '$want'" >&2; exit 1; }
done

changed=0
skipped=0

for agent in $AGENTS; do
    label="${agent%%:*}"
    home="${agent#*:}"
    dir="$home/skills"
    echo "$label"

    if [ ! -d "$home" ]; then
        echo "  skipped ($(short "$home") not found)"
        continue
    fi

    while read -r name; do
        [ -n "$name" ] || continue
        listed "$name" "$@" || continue
        src="$SRC/$name"
        dest="$dir/$name"

        if ! listed "$label" $(targets_of "$name"); then
            if [ -f "$dest/$MARKER" ]; then
                rm -rf "$dest"
                echo "  $name: removed (not installed into $label)"
                changed=1
            fi
            continue
        fi

        if [ -e "$dest" ] && [ ! -f "$dest/$MARKER" ]; then
            if diff -rq "$src" "$dest" >/dev/null 2>&1; then
                printf '%s\n' "$STAMP" > "$dest/$MARKER"
                echo "  $name: adopted (already identical)"
                changed=1
            else
                echo "  $name: skipped ($(short "$dest") differs and was not installed by this config)"
                skipped=1
            fi
            continue
        fi
        if [ -d "$dest" ] \
            && [ "$(cat "$dest/$MARKER")" = "$STAMP" ] \
            && diff -rq -x "$MARKER" "$src" "$dest" >/dev/null 2>&1; then
            echo "  $name: unchanged"
            continue
        fi

        if [ -e "$dest" ]; then verb=updated; else verb=installed; fi
        rm -rf "$dest"
        mkdir -p "$dir"
        cp -R "$src" "$dest"
        printf '%s\n' "$STAMP" > "$dest/$MARKER"
        echo "  $name: $verb"
        changed=1
    done <<< "$skills"

    # Prune only on a full install, where the list is known to be complete.
    [ "$#" -eq 0 ] || continue
    for dest in "$dir"/*/; do
        dest="${dest%/}"
        [ -f "$dest/$MARKER" ] || continue
        name="$(basename "$dest")"
        printf '%s\n' "$skills" | awk -v n="$name" '$1 == n { f = 1 } END { exit !f }' && continue
        rm -rf "$dest"
        echo "  $name: removed (no longer in this repo)"
        changed=1
    done
done

echo
if [ "$changed" -eq 1 ]; then
    echo "Done. Start a new Claude Code or Codex session to pick up the changes."
elif [ "$skipped" -eq 0 ]; then
    echo "Nothing to do -- already installed."
fi
if [ "$skipped" -eq 1 ]; then
    echo "Some skills were skipped. Move the folders named above aside and re-run to install them."
fi
