# Layout

Each top-level directory holds one kind of configuration and installs on its own. No script installs everything at once. Name a new top-level directory after what it holds, not after how it installs.

`claude/` is the Claude Code configuration. Each subdirectory is one feature that `claude/install.sh` merges into `~/.claude`.

`skills/` holds every skill as `skills/<name>/`, installed into both Claude Code and Codex by `skills/install.sh`. See `docs/writing-skills.md`.

`terminal/` holds terminal app configuration, one subdirectory per app. Each app has its own `install.sh` and `Brewfile`, and `terminal/install.sh` runs them all. Keep each app installable alone, so a file that ties two apps together belongs to the app that needs it and the other app includes it as optional.

`experimental/` holds tools still being built. Nothing installs them. Move a tool out of it once it gets an installer.
