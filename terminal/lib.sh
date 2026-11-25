# Shared by ghostty/install.sh and herdr/install.sh. Sourced, not run.
#
# The caller sets SRC to its own directory, and reads $changed once done.

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

changed=0

short() {  # path under $HOME -> ~/...
    printf '~%s' "${1#"$HOME"}"
}

brew_bundle() {  # Brewfile
    command -v brew >/dev/null 2>&1 \
        || { echo "error: Homebrew is required (https://brew.sh), or pass --no-deps" >&2; exit 1; }
    echo "brew bundle"
    if brew bundle check --file="$1" >/dev/null 2>&1; then
        echo "  already satisfied"
    else
        brew bundle install --file="$1"
        changed=1
    fi
}

# {{HOME}} in a source file is replaced with $HOME on the way out, since neither
# herdr's command paths nor Ghostty's config-file take a shell variable.
#
# These files are the whole config, not fragments: a destination that differs
# is copied to <name>.bak.<timestamp> and then overwritten.
install_file() {  # src dest
    local src="$1" dest="$2" rendered="$work/rendered"
    local label
    label="$(short "$dest")"

    sed "s|{{HOME}}|$HOME|g" "$src" > "$rendered"

    if cmp -s "$rendered" "$dest" 2>/dev/null; then
        echo "  $label: unchanged"
        return
    fi
    mkdir -p "$(dirname "$dest")"
    if [ -e "$dest" ]; then
        cp -p "$dest" "$dest.bak.$(date +%Y%m%d%H%M%S)"
        echo "  $label: updated (backup written alongside it)"
    else
        echo "  $label: installed"
    fi
    if [ -x "$src" ]; then install -m 0755 "$rendered" "$dest"; else install -m 0644 "$rendered" "$dest"; fi
    changed=1
}

parse_args() {  # "$@" -> sets deps
    deps=1
    for arg in "$@"; do
        case "$arg" in
            --no-deps) deps=0 ;;
            -h|--help) usage; exit 0 ;;
            *) echo "error: unknown option: $arg" >&2; usage >&2; exit 1 ;;
        esac
    done
}
