---
name: orch
description: Orchestrate claude or codex agents in Herdr panes -- open a pane next to the caller, start an agent in it, send prompts, and read back only the agent's final reply (no tool calls, progress lines or terminal UI). Also stops those agents and closes their panes. Use when the user invokes orch or asks to run, ask, or stop a claude/codex agent in a Herdr pane.
argument-hint: "What should the agents do -- or 'stop' to shut down the agents orch started?"
---

# orch

Everything goes through one script, `scripts/orch.sh`, next to this file. It wraps the Herdr CLI and reads replies from each agent's session transcript rather than its screen, so a reply contains only what the agent wrote as its answer.

**Keep your own context clean.** That is the point of this skill: the script does the looking-up, and prints a few lines instead of pouring help pages, JSON catalogues or terminal screens into your session. So:

- This document is the complete interface. Do not run `herdr --help`, `herdr <group>` without a subcommand, `herdr --skill`, or `orch.sh --help` to discover syntax.
- Do not run agent CLIs directly for information (`codex debug models`, `claude --help`); `orch.sh models` answers that in a few lines.
- Delegated work belongs in the delegate's context, not yours. Give it a written brief, ask for a short answer, and use `--out` when the answer itself would be long.

```bash
ORCH="<directory of this SKILL.md>/scripts/orch.sh"   # ~/.claude/skills/orch/... or ~/.codex/skills/orch/...
```

## 0. Preconditions

```bash
test "${HERDR_ENV:-}" = 1
```

If it fails, tell the user you are not running inside a Herdr pane and stop. `jq` must be installed. Only `claude` and `codex` agents are supported.

## 1. Start agents -- `up`

```bash
"$ORCH" up <name> --kind claude|codex [--cwd DIR] [--direction right|down] [-- AGENT_ARGS...]
```

- **name**: lowercase, matching `^[a-z][a-z0-9_-]{0,31}$`, unique among live agents. Pick names by role (`reviewer`, `impl-codex`).
- **Where the pane opens**:
  - The first agent splits the pane you are running in: to the right when it is at least twice as wide as tall, otherwise downward. Later agents stack downward under the newest orch pane, so columns do not keep halving.
  - Pass `--direction` only when the user asks for a direction.
  - Focus stays in your pane.
- **Working directory**: defaults to your current directory (`$PWD`). Pass `--cwd` only when the user names another path; relative paths resolve against your directory, and the path must exist. Do not create worktrees, tabs or workspaces.
- **AGENT_ARGS**: native CLI flags for the agent, after `--`. Pass none unless the user asks for something specific; without them each agent uses the user's own defaults.

Model and reasoning level are such flags, and they combine with `--cwd`: orch's own options come first, the agent's after `--`.

```bash
"$ORCH" up reviewer --kind claude --cwd /path/to/repo -- --model sonnet --effort low
"$ORCH" up impl --kind codex --cwd /path/to/repo -- --model gpt-5.6-sol -c model_reasoning_effort=high
```

Ask the script what is available rather than guessing, or running the agent CLIs yourself:

```bash
"$ORCH" models          # both kinds; or: models claude / models codex
```

It prints one line per model with its selectable reasoning levels, plus the user's current defaults and how codex takes a level. Values come from the installed agents, so they stay correct as those change. A wrong value makes the agent fail to start, and `up` then prints the pane's screen with the error.

On success it prints one tab-separated line: `name  kind  pane_id  status  cwd`. It returns only once the agent is ready for input.

Start several agents by calling `up` once per agent, one after another -- not in parallel, because placement reads the panes created before it.

## 2. Ask -- `ask`

```bash
"$ORCH" ask <name> "<prompt>" [--timeout MS]
printf '%s' "$long_prompt" | "$ORCH" ask <name> -      # prompt from stdin
```

Sends the prompt, waits for the turn to finish, and prints **only the final reply** of that turn on stdout. Diagnostics go to stderr.

- **Reply source**: the reply is checked against the transcript to belong to this very turn.
  - claude: the text written after its last tool call.
  - codex: `last_agent_message`.
  - Interim sentences ("I'll look at X first"), tool calls, tool output and screen chrome are never included.
- **Blocking**: `ask` returns only when that turn is done, so your own session waits. To keep working meanwhile, use `send` instead (section B), or `handoff` when you will not follow up at all (section C).
- **Timeout**: default 30 minutes. Pass a larger `--timeout` for long tasks.
- **Parallel work**: asks to *different* agents can run in parallel (`&` + `wait`). Never send two asks to the same agent at once.
- **Long replies**: `--out FILE` writes the reply to FILE and prints only `wrote FILE (n lines, n bytes)`, so a long answer never lands in your context. Read the file only if you actually need its content. Works on `ask`, `wait` and `reply`.

Write prompts that are complete on their own; the agent sees nothing of your conversation.

## 3. Exit codes and what to do

On any non-zero exit, stdout is empty -- nothing that is not a reply is ever printed there.

| code | meaning | do this |
|---|---|---|
| 0 | reply printed | use it |
| 1 | error (message on stderr) | read the message; `status` shows the agent's state |
| 2 | usage error | fix the command |
| 3 | **blocked** -- the agent shows an approval or question dialog; the screen is printed on stderr | Show the user what it asks and get their decision. Answer with `keys` (e.g. claude's numbered choices: `keys <name> 1` to accept, `esc` to decline), then run `wait`. Never approve on your own. |
| 4 | **timeout** -- the agent may still be working | `wait <name>` (optionally with a longer `--timeout`). Do not resend the prompt. |
| 5 | **not submitted?** -- the prompt was typed but no activity followed, or the agent settled without recording a new turn; the screen is printed | Look at the screen. If your prompt does not appear as a sent message (a startup dialog may have swallowed it), clear leftovers with `keys <name> esc` and `ask` once more. If it did go through, `wait <name>`. If it is unclear, ask the user. Never resend blindly. |
| 6 | **busy** -- the agent is still working on an earlier turn | `wait <name>` first |

A turn that is declined or interrupted may end without any text; `wait` then exits 1 saying so, and the agent is ready for the next `ask`.

## 4. Other commands

```bash
"$ORCH" send <name> "<prompt>"        # prompt without waiting; collect later with wait
"$ORCH" wait <name> [--timeout MS]   # wait for the current turn, print its final reply (exits 1 if nothing is in progress)
"$ORCH" reply <name>                 # print the last completed turn's final reply again
"$ORCH" status [name]                # agents orch started from this pane; REPLY is waiting|ready for a sent prompt
"$ORCH" models [claude|codex]        # available models, reasoning levels and current defaults
"$ORCH" handoff <name> --kind ...    # start an independent agent orch will not track or close (section C)
"$ORCH" screen <name> [--lines N]    # raw terminal text, for diagnosing blocked/stalled only
"$ORCH" keys <name> <key>...         # send keys: esc, enter, tab, up, down, ctrl+c, y, n, 1, 2 ...
```

`status` values:

| value | meaning |
|---|---|
| `idle`, `done` | ready for input |
| `working` | still on a turn |
| `blocked` | waiting at a dialog |
| `unknown` | agent present but Herdr cannot classify its state; for codex, orch reads idle or working from its transcript instead, so codex never shows this |
| `exited(pane open)` | the agent quit and its pane is still open |
| `pane-closed` | the pane is gone |

Never use `screen` output as the agent's answer; use `ask`/`wait`/`reply`.

## 5. The three ways this is used

A handoff comes in two shapes -- one that stays attached to your session (B) and one that leaves it for good (C). Ask which is meant when it is not clear.

### A. Dispatch work and use the answer

A review, a second opinion, a self-contained question whose answer you need before continuing.

```bash
"$ORCH" up reviewer --kind codex
"$ORCH" ask reviewer "Review the diff of HEAD in $PWD for correctness bugs. Reply with findings only: file:line, what breaks, why." --out /tmp/review.md
```

`ask` waits for the turn, so use it when the answer is what you need next. Asks to different agents can run at the same time.

### B. Hand off, keep working, collect later (still yours)

Something has to happen alongside your work and its result still matters to you. Send the brief without waiting, carry on, and collect when you need it.

```bash
"$ORCH" up side-task --kind claude --cwd /path/to/repo
"$ORCH" send side-task "Read /tmp/brief-side-task.md and carry it out. When done, reply with at most 10 lines: what changed, which files, what is left."
# ... your own work continues here ...
"$ORCH" status                                   # REPLY column: waiting | ready
"$ORCH" wait side-task --out /tmp/side-result.md # collect when ready (or block until it is)
```

`send` returns as soon as the agent starts the turn. These agents stay tracked: `status` lists them, and `down` closes them when the task is done or the user asks.

Write the brief to a file -- goal, absolute paths, constraints, what "done" means, what to leave alone -- so the agent needs nothing from your conversation. The `handoff` skill writes exactly this kind of document.

### C. Hand off for good (no longer yours)

The task leaves your hands entirely: the user drives that pane from here on, and its session outlives your work.

```bash
"$ORCH" handoff bugfix --kind claude --cwd /path/to/repo --brief /tmp/brief-bugfix.md
"$ORCH" handoff bugfix --kind codex --prompt "..."          # or an inline brief
```

Options: `--cwd`, `--direction` and `-- AGENT_ARGS` behave as in `up`. Focus stays with you; the pane id is printed, so the user can switch to it when they want.

It returns as soon as the agent has taken the brief and prints `name  kind  pane_id  cwd`. From then on:

- `status` never lists it, and `ask`, `send`, `wait` and `reply` do not accept it.
- **`down` never closes it**, `--all` included. Only the user ends that session.

Say in the brief that the agent should ask the user -- not you -- when something is unclear, and report back to the user in its own pane.

## 6. Agents live as long as the task

Keep an agent you started with `up` open until its task ends, so later rounds reuse the context it already has. A task that goes from plan through plan review, implementation, code review and PR to merge ends at merge, not after one review. Any other task ends when you report its final result.

When the task ends, close its agents with `down <name>`. Do not use `--all` here, because `status` also lists agents from other tasks in this pane.

Keep them open when the user asks.

## 7. Stop -- `down`

Run this when a task ends (section 6) or when the user asks to stop the orch agents. Use `--all` only when the user asks to close all of them.

```bash
"$ORCH" down --all             # every agent orch started from this pane
"$ORCH" down <name> [<name>...]
```

For each agent it:
1. sends ctrl+c until the agent process exits (codex exits on the first press, claude on the second);
2. closes the pane;
3. forgets the agent.

An agent in the middle of a turn is interrupted, so if `status` shows `working`, tell the user before stopping unless they already said to stop regardless.

`down` touches only panes orch recorded as started from the current pane. It never closes panes or agents you did not start through orch, even when their names look similar.

## Scope of "this pane"

orch records agents under `${XDG_STATE_HOME:-~/.local/state}/orch/<herdr server>/<caller pane id>/<name>.json`. A later session in the same Herdr pane sees and can stop them. From a different pane they are invisible; if the user wants to manage them from there, set `ORCH_OWNER=<original pane id>` for those calls (the pane id is in the `up` output).

## Internals

Only if something misbehaves and you need to know what the script does underneath -- the Herdr calls it makes, the transcript records it reads, how a reply is proven to belong to its turn, and what is still unverified: read `reference/internals.md` next to this file. Normal work never needs it.
