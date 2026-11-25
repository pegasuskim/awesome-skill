# Writing skills

Skills live in `skills/<name>/SKILL.md`. Edit them here, not the copies `skills/install.sh` places in `~/.claude/skills` and `~/.codex/skills`.

A skill installs into both Claude Code and Codex unless `skills/install.json` names which ones, so write for every agent it installs into. Name no tool that only one of them has, and find files relative to the SKILL.md rather than under `~/.claude`. The two agents read invocation settings from different places. For a skill that must run only when the user calls it, set `disable-model-invocation: true` in the frontmatter for Claude Code, and add `agents/openai.yaml` with `policy.allow_implicit_invocation: false` for Codex.

Write instructions so they have only one reading. Keep only sentences that change what the agent does or how it judges.

When a skill refers to another skill, check that the other skill actually says what is claimed, and that its frontmatter lets the agent invoke it.
