# orch internals

This section is for debugging only; normal work uses the commands above.

| step | Herdr call | reads |
|---|---|---|
| placement | `herdr pane layout --pane <caller>` | `.result.layout.panes[].rect.width/height` |
| open pane | `herdr pane split --pane <anchor> --direction <d> --cwd <dir> --no-focus` | `.result.pane.pane_id` |
| start | `herdr agent start <name> --kind <kind> --pane <pane> --timeout 60000 [-- args]` | error `agent_not_ready` means blocked at startup; codex always gets `--no-daemon` |
| state | `herdr agent get <name>` | `.result.agent.agent_status`, `.result.agent.agent_session.value` |
| prompt (`ask`) | `herdr agent prompt <name> <text> --wait --timeout <ms>`; codex uses `--until working --until blocked --timeout 20000` | errors `agent_prompt_stalled`, `timeout`, `agent_blocked` |
| prompt (`send`, `handoff`) | same call with `--wait --until working --timeout 20000` | returns once the turn starts; the turn runs on |
| wait | `herdr agent wait <name> [--timeout ms]`; skipped for codex | settles on idle, done or blocked |
| screen | `herdr agent read <name> --source recent-unwrapped --lines N` | |
| keys | `herdr agent send-keys <name> <key>...` | |
| stop | `herdr agent send-keys <name> ctrl+c`, then `herdr pane close <pane>` | |

Where replies come from:

- **claude**: `~/.claude/projects/*/<session id>.jsonl`.
  - A turn ends with a `{"type":"system","subtype":"turn_duration"}` record.
  - The reply is the assistant `text` blocks after the last `user` record (the prompt or a tool result) before that marker.
- **codex**: `~/.codex/sessions/**/rollout-*-<session id>.jsonl`.
  - A turn ends with `event_msg` / `task_complete`.
  - The reply is its `payload.last_agent_message`.
  - Codex reports a session id only once its first prompt is written.
  - Herdr reports a codex waiting for input as `unknown` and never sees its turn end. orch reads idle or working from the transcript instead, and `ask` and `wait` poll the transcript for the end of the turn.
  - A codex attached to the shared app-server daemon reports its session id to the pane that started the daemon, so orch starts codex with `--no-daemon`.

Before prompting, `ask` records the transcript's completed-turn count. It prints a reply only after that count has grown, so it never returns an earlier turn's answer.

Not yet verified: that the session id and transcript stay continuous after an agent compacts a long conversation. If `ask` fails with "no new completed turn" after a long session, check `status` and `screen`, and tell the user.

`send` records the same baseline `ask` does, so a later `wait` still proves the reply belongs to that prompt, and `status` compares the baseline with the transcript to show `waiting` or `ready`.

`handoff` starts an agent through the same path as `up` and then deletes its state file, which is what makes it invisible to `status`, `ask`, `send`, `wait`, `reply` and `down`. Herdr still knows the agent by name; only orch has let go of it.
