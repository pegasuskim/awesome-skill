#!/usr/bin/env bash
#
# Installs the shared Claude Code configuration into ~/.claude.
#
# Layout: one directory per feature. Each may contain
#
#   settings.json   keys merged into ~/.claude/settings.json
#   CLAUDE.md       inserted into ~/.claude/CLAUDE.md as a marked block
#   files/          mirror of ~/.claude, copied verbatim
#
# Adding a feature means adding a directory; this script needs no edit.
#
# Idempotent: re-running makes no further changes. Only what a feature
# declares is touched -- every other setting, hook and note the user already
# has is left alone.
#
# Paths are fixed to ~/.claude so they stay in sync with the commands declared
# in the settings fragments. CLAUDE_CONFIG_DIR is not honoured.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
MEMORY="$CLAUDE_DIR/CLAUDE.md"

# Appended to every hook command this script writes, so a later run can find
# what it owns even after the command itself changes.
MARK=" # claude-config"

command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 1; }

mkdir -p "$CLAUDE_DIR"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

changed=0

copy_if_changed() {  # src dest label
    if cmp -s "$1" "$2" 2>/dev/null; then
        echo "  $3: unchanged"
    else
        mkdir -p "$(dirname "$2")"
        if [ -x "$1" ]; then install -m 0755 "$1" "$2"; else install -m 0644 "$1" "$2"; fi
        echo "  $3: installed"
        changed=1
    fi
}

backup() {  # path
    [ -f "$1" ] && cp "$1" "$1.bak.$(date +%Y%m%d%H%M%S)"
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
            copy_if_changed "$f" "$CLAUDE_DIR/$rel" "$rel"
        done < <(find "$feature_dir/files" -type f ! -name '.DS_Store' | sort)
    fi

    if [ -f "$feature_dir/CLAUDE.md" ]; then
        begin="<!-- BEGIN managed by claude-config: $feature -->"
        end="<!-- END managed by claude-config: $feature -->"
        block="$work/block.md"
        merged="$work/memory.md"

        { printf '%s\n' "$begin"; cat "$feature_dir/CLAUDE.md"; printf '%s\n' "$end"; } > "$block"
        [ -f "$MEMORY" ] || : > "$MEMORY"

        awk -v begin="$begin" -v end="$end" -v blockfile="$block" '
            BEGIN { while ((getline line < blockfile) > 0) blk = blk line "\n" }
            $0 == begin { found = 1; skip = 1; printf "%s", blk; next }
            $0 == end   { skip = 0; next }
            !skip       { print; last_blank = ($0 == "") }
            END { if (!found) { if (NR > 0 && !last_blank) print ""; printf "%s", blk } }
        ' "$MEMORY" > "$merged"

        if cmp -s "$merged" "$MEMORY"; then
            echo "  CLAUDE.md: unchanged"
        else
            backup "$MEMORY"
            cat "$merged" > "$MEMORY"
            echo "  CLAUDE.md: updated (backup written alongside it)"
            changed=1
        fi
    fi
done

# --- settings.json ---------------------------------------------------------
# Every feature's settings.json is folded into one fragment first: plain keys
# merge recursively, hook events concatenate.
fragments=("$SRC"/*/settings.json)
if [ -e "${fragments[0]}" ]; then
    combined="$work/combined.json"
    jq -s '
        reduce .[] as $f ({};
            . as $acc
            | ($acc * ($f | del(.hooks)))
            | .hooks = (reduce (($f.hooks // {}) | keys_unsorted[]) as $ev
                          (($acc.hooks // {}); .[$ev] = ((.[$ev] // []) + $f.hooks[$ev]))))
        | if (.hooks | length) == 0 then del(.hooks) else . end
    ' "${fragments[@]}" > "$combined"

    [ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
    jq -e . "$SETTINGS" >/dev/null 2>&1 \
        || { echo "error: $SETTINGS is not valid JSON -- fix it first" >&2; exit 1; }

    # Plain keys replace outright, except "env", which merges per variable so a
    # user's own environment entries survive. Per hook event, the entries this
    # script owns
    # are dropped first, then ours appended -- so re-running never duplicates,
    # and hooks the user added on the same event survive.
    #
    # Ownership is the marker, not the command text, so renaming a hook script
    # or reworking its command still lets the next run replace the old entry.
    # Hook types that carry no command (prompt, agent, http, mcp_tool) cannot be
    # marked, so those fall back to matching the entry itself.
    jq --indent 2 --arg mark "$MARK" --slurpfile frag "$combined" '
        ($frag[0]
          | if has("hooks") then
                .hooks |= with_entries(.value |= map(.hooks |= map(
                    if has("command") and ((.command | contains($mark)) | not)
                    then .command += $mark else . end)))
            else . end) as $f
        | (.hooks //= {})
        | reduce (($f.hooks // {}) | keys_unsorted[]) as $ev (.;
            ([$f.hooks[$ev][].hooks[]]) as $ours
            | .hooks[$ev] = (
                ((.hooks[$ev] // [])
                  | map(.hooks |= map(select(
                        (((.command // "") | contains($mark))
                         or ((. as $e | $ours | index($e)) != null)) | not)))
                  | map(select((.hooks | length) > 0)))
                + $f.hooks[$ev]
              ))
        | reduce (($f | del(.hooks) | del(.env)) | keys_unsorted[]) as $k (.; .[$k] = $f[$k])
        | if ($f | has("env")) then .env = ((.env // {}) * $f.env) else . end
    ' "$SETTINGS" > "$work/settings.json"

    echo "settings.json"
    if cmp -s "$work/settings.json" "$SETTINGS"; then
        echo "  already up to date"
    else
        backup "$SETTINGS"
        cat "$work/settings.json" > "$SETTINGS"
        echo "  updated (backup written alongside it)"
        changed=1
    fi
fi

echo
if [ "$changed" -eq 1 ]; then
    echo "Done. Open /hooks once or restart Claude Code to pick up the changes."
else
    echo "Nothing to do -- already installed."
fi
