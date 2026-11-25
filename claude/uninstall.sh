#!/usr/bin/env bash
#
# Removes what install.sh put into ~/.claude.
#
# Reads the same feature directories install.sh does, so adding a feature needs
# no edit here either. Per feature:
#
#   files/          every declared path is deleted, and a directory our own
#                   deletions emptied is then removed
#   CLAUDE.md       the block marked for that feature is cut out
#   settings.json   hook entries carrying the marker are dropped, and the keys
#                   and env variables the fragments declare are deleted
#
# Only what a feature declares is touched. Files someone else put under a
# directory this config created stay, and that directory stays with them.
#
# One asymmetry is unavoidable. install.sh replaces plain keys outright and
# records nothing about what they held before, so this can delete such a key but
# never restore the value it displaced. The backups install.sh writes next to
# settings.json are the only record of those, and clean-backup.sh is what
# removes them -- so run this first if you want that option left open.
#
# Idempotent: re-running makes no further changes. CLAUDE.md and settings.json
# are backed up before being rewritten, the same convention install.sh follows.
#
# Usage:
#   uninstall.sh             remove
#   uninstall.sh --dry-run   report what would change; touch nothing
#
# Paths are fixed to ~/.claude so they stay in step with install.sh.
# CLAUDE_CONFIG_DIR is not honoured.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
MEMORY="$CLAUDE_DIR/CLAUDE.md"

# The marker install.sh appends to every hook command it writes. Ownership is
# the marker, not the command text, so a hook whose command was later reworked
# is still recognised here.
MARK=" # claude-config"

dry_run=0

usage() {
    cat <<'USAGE'
Usage:
  uninstall.sh             remove
  uninstall.sh --dry-run   report what would change; touch nothing
USAGE
}

if [ "$#" -gt 0 ]; then
    for arg in "$@"; do
        case "$arg" in
            --dry-run) dry_run=1 ;;
            -h|--help) usage; exit 0 ;;
            *) echo "error: unknown option: $arg" >&2; usage >&2; exit 1 ;;
        esac
    done
fi

command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 1; }

[ -d "$CLAUDE_DIR" ] || { echo "Nothing to do -- $CLAUDE_DIR does not exist."; exit 0; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
: > "$work/dirs"

changed=0

backup() {  # path
    [ "$dry_run" -eq 1 ] && return 0
    [ -f "$1" ] && cp "$1" "$1.bak.$(date +%Y%m%d%H%M%S)"
    return 0
}

# --- per feature: files/ and CLAUDE.md -------------------------------------
for feature_dir in "$SRC"/*/; do
    feature_dir="${feature_dir%/}"
    feature="$(basename "$feature_dir")"
    [ -d "$feature_dir" ] || continue
    echo "$feature"

    if [ -d "$feature_dir/files" ]; then
        while IFS= read -r f; do
            rel="${f#"$feature_dir/files/"}"
            dest="$CLAUDE_DIR/$rel"
            if [ -e "$dest" ]; then
                if [ "$dry_run" -eq 1 ]; then
                    echo "  $rel: would remove"
                else
                    rm -f "$dest"
                    echo "  $rel: removed"
                fi
                dirname "$dest" >> "$work/dirs"
                changed=1
            else
                echo "  $rel: absent"
            fi
        done < <(find "$feature_dir/files" -type f ! -name '.DS_Store' | sort)
    fi

    if [ -f "$feature_dir/CLAUDE.md" ] && [ -f "$MEMORY" ]; then
        begin="<!-- BEGIN managed by claude-config: $feature -->"
        end="<!-- END managed by claude-config: $feature -->"

        if ! grep -Fxq "$begin" "$MEMORY"; then
            echo "  CLAUDE.md: no block found"
        else
            stripped="$work/memory.md"
            # Cut the block, then drop the blank lines it leaves at the end --
            # install.sh adds one before appending a block.
            awk -v begin="$begin" -v end="$end" '
                $0 == begin { skip = 1; next }
                $0 == end   { skip = 0; next }
                !skip       { print }
            ' "$MEMORY" \
            | awk '
                { line[NR] = $0 }
                END {
                    last = NR
                    while (last > 0 && line[last] ~ /^[[:space:]]*$/) last--
                    for (i = 1; i <= last; i++) print line[i]
                }
            ' > "$stripped"

            if [ "$dry_run" -eq 1 ]; then
                echo "  CLAUDE.md: would remove block"
            else
                backup "$MEMORY"
                cat "$stripped" > "$MEMORY"
                echo "  CLAUDE.md: block removed (backup written alongside it)"
            fi
            changed=1
        fi
    fi
done

# --- settings.json ---------------------------------------------------------
# The fragments are folded together exactly as install.sh folds them, so what
# gets deleted here is precisely what got written there.
fragments=("$SRC"/*/settings.json)
if [ -e "${fragments[0]}" ] && [ -f "$SETTINGS" ]; then
    jq -e . "$SETTINGS" >/dev/null 2>&1 \
        || { echo "error: $SETTINGS is not valid JSON -- fix it first" >&2; exit 1; }

    combined="$work/combined.json"
    jq -s '
        reduce .[] as $f ({};
            . as $acc
            | ($acc * ($f | del(.hooks)))
            | .hooks = (reduce (($f.hooks // {}) | keys_unsorted[]) as $ev
                          (($acc.hooks // {}); .[$ev] = ((.[$ev] // []) + $f.hooks[$ev]))))
        | if (.hooks | length) == 0 then del(.hooks) else . end
    ' "${fragments[@]}" > "$combined"

    # Hooks go by marker, falling back to matching the entry itself for the hook
    # types that carry no command. Plain keys and env variables go by name; the
    # user's own entries on the same event, and their other env variables, are
    # left untouched.
    jq --indent 2 --arg mark "$MARK" --slurpfile frag "$combined" '
        $frag[0] as $f
        | (.hooks //= {})
        | reduce (($f.hooks // {}) | keys_unsorted[]) as $ev (.;
            ([$f.hooks[$ev][].hooks[]]) as $ours
            | .hooks[$ev] = (
                ((.hooks[$ev] // [])
                  | map(.hooks |= map(select(
                        (((.command // "") | contains($mark))
                         or ((. as $e | $ours | index($e)) != null)) | not)))
                  | map(select((.hooks | length) > 0)))
              ))
        | .hooks |= with_entries(select((.value | length) > 0))
        | (if (.hooks | length) == 0 then del(.hooks) else . end)
        | reduce (($f | del(.hooks) | del(.env)) | keys_unsorted[]) as $k (.; del(.[$k]))
        | (if ($f | has("env")) and has("env")
           then reduce ($f.env | keys_unsorted[]) as $k (.; del(.env[$k]))
           else . end)
        | (if has("env") and ((.env | length) == 0) then del(.env) else . end)
    ' "$SETTINGS" > "$work/settings.json"

    echo "settings.json"
    if cmp -s "$work/settings.json" "$SETTINGS"; then
        echo "  nothing of this config's is present"
    elif [ "$dry_run" -eq 1 ]; then
        echo "  would remove this config's entries"
        changed=1
    else
        backup "$SETTINGS"
        cat "$work/settings.json" > "$SETTINGS"
        echo "  updated (backup written alongside it)"
        changed=1
    fi
fi

# --- directories our own deletions emptied ---------------------------------
# Deepest first, and never $CLAUDE_DIR itself. rmdir refuses a directory that
# still holds anything, which is exactly the guard wanted here.
if [ "$dry_run" -eq 0 ] && [ -s "$work/dirs" ]; then
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        [ "$d" = "$CLAUDE_DIR" ] && continue
        if rmdir "$d" 2>/dev/null; then
            echo "removed empty directory: ${d#"$CLAUDE_DIR"/}"
        fi
    done < <(sort -ru "$work/dirs")
fi

echo
if [ "$changed" -eq 1 ]; then
    if [ "$dry_run" -eq 1 ]; then
        echo "Dry run -- nothing was changed."
    else
        echo "Done. Restart Claude Code to pick up the changes."
    fi
else
    echo "Nothing to do -- this config is not installed."
fi
