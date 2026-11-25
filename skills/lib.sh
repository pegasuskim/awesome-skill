# Shared by install.sh and uninstall.sh. Sourced, not run.

# Each agent's user-level skills directory, used only when the agent's own
# directory exists. ~/.claude is fixed, as in claude/install.sh. Codex honours
# CODEX_HOME, and its bundled skill-installer writes to $CODEX_HOME/skills too.
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
AGENTS="claude:$HOME/.claude codex:$CODEX_DIR"

# Written into every skill folder this config installs. Only folders carrying
# it are ever replaced or removed, so a skill someone put there by hand under
# the same name is left alone.
MARKER=".managed-by-awesome-config"

short() {  # path under $HOME -> ~/...
    case "$1" in
        "$HOME"/*) printf '~%s' "${1#"$HOME"}" ;;
        *) printf '%s' "$1" ;;
    esac
}

listed() {  # name [names...] -> true when no names are given or name is one of them
    local name="$1"
    shift
    [ "$#" -eq 0 ] && return 0
    local n
    for n in "$@"; do
        [ "$n" = "$name" ] && return 0
    done
    return 1
}
