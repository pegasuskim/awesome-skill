#!/usr/bin/env bash
#
# orch -- start claude/codex agents in Herdr panes, talk to them, and read back
# only their final reply.
#
# The reply is never scraped from the terminal. Each agent writes a session
# transcript, and Herdr reports that session's id; the reply is read from there,
# so tool calls, progress lines and UI chrome cannot leak into it.
#
#   claude  $CLAUDE_CONFIG_DIR/projects/*/<sid>.jsonl   (default ~/.claude)
#           a turn ends with {"type":"system","subtype":"turn_duration"}
#   codex   $CODEX_HOME/sessions/**/rollout-*-<sid>.jsonl  (default ~/.codex)
#           a turn ends with event_msg/task_complete, carrying last_agent_message
#
# Every agent started here is recorded under $ORCH_STATE_DIR, keyed by the Herdr
# server and the pane that started it. `down` only ever touches recorded panes.
#
# Exit codes: 0 ok, 1 error, 2 usage, 3 blocked, 4 timeout, 5 prompt stalled,
#             6 agent busy.
#
# Written for the bash 3.2 that ships with macOS.

set -euo pipefail

PROG="orch"
NAME_RE='^[a-z][a-z0-9_-]{0,31}$'
DEFAULT_ASK_TIMEOUT_MS=1800000
START_TIMEOUT_MS=60000
TRANSCRIPT_GRACE_S=30
CLAUDE_HOME="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"

usage() {
    cat <<'USAGE'
Usage:
  orch.sh up <name> --kind claude|codex [--cwd DIR] [--direction right|down] [-- AGENT_ARGS...]
  orch.sh handoff <name> --kind claude|codex [--cwd DIR] [--direction right|down]
                         [--brief FILE | --prompt TEXT] [-- AGENT_ARGS...]
  orch.sh ask <name> <prompt|-> [--timeout MS]
  orch.sh send <name> <prompt|->
  orch.sh wait <name> [--timeout MS]
  orch.sh reply <name>
  orch.sh screen <name> [--lines N]
  orch.sh keys <name> <key>...
  orch.sh status [name]
  orch.sh models [claude|codex]
  orch.sh down <name>... | --all

Options for ask/wait/reply:
  --out FILE   write the reply to FILE and print only its path and size
USAGE
}

die()  { echo "$PROG: $*" >&2; exit 1; }
bail() { local code="$1"; shift; echo "$PROG: $*" >&2; exit "$code"; }
usage_error() { echo "$PROG: $*" >&2; usage >&2; exit 2; }

require_env() {
    command -v jq >/dev/null 2>&1 || die "jq is required"
    command -v herdr >/dev/null 2>&1 || die "herdr is not in PATH"
    [ "${HERDR_ENV:-}" = 1 ] || die "not running inside a Herdr pane (HERDR_ENV != 1)"
    [ -n "${HERDR_PANE_ID:-}" ] || die "HERDR_PANE_ID is not set"
}

# --- herdr calls -------------------------------------------------------------
# herdr prints results as JSON on stdout and errors as JSON on stderr (exit 1).
# HOUT holds whichever came back; the return status is herdr's.
HOUT=""
hcall() {
    local rc=0
    HOUT="$(herdr "$@" 2>&1)" || rc=$?
    return "$rc"
}
herr_code() { jq -r '.error.code // empty' <<<"$HOUT" 2>/dev/null || true; }
herr_msg()  { jq -r '.error.message // empty' <<<"$HOUT" 2>/dev/null || printf '%s' "$HOUT"; }

# --- state -------------------------------------------------------------------
state_dir() {
    local server owner
    server="$(printf '%s' "${HERDR_SOCKET_PATH:-default}" | shasum | cut -c1-12)"
    owner="$(printf '%s' "${ORCH_OWNER:-$HERDR_PANE_ID}" | tr -c 'A-Za-z0-9_-' '_')"
    printf '%s/%s/%s' "${ORCH_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/orch}" "$server" "$owner"
}
state_file() { printf '%s/%s.json' "$(state_dir)" "$1"; }
state_get()  { jq -r "$2" "$(state_file "$1")"; }
state_set() {  # name jq-filter [jq args...]
    local f tmp
    f="$(state_file "$1")"; shift
    tmp="$f.tmp.$$"
    jq "$@" "$f" > "$tmp" && mv "$tmp" "$f"
}
require_managed() {
    [[ "$1" =~ $NAME_RE ]] || usage_error "invalid name: $1 (must match $NAME_RE)"
    [ -f "$(state_file "$1")" ] || die "no agent named '$1' was started by orch from this pane (see: orch.sh status)"
}
managed_names() {
    local d f
    d="$(state_dir)"
    [ -d "$d" ] || return 0
    for f in "$d"/*.json; do
        [ -e "$f" ] || continue
        basename "$f" .json
    done
}

pane_alive() { hcall pane get "$1"; }

# --- transcripts -------------------------------------------------------------
agent_sid() {  # name -> session id or empty
    hcall agent get "$1" || return 0
    jq -r '.result.agent.agent_session.value // empty' <<<"$HOUT"
}
agent_status() {  # name -> status, or "gone"
    if hcall agent get "$1"; then
        jq -r '.result.agent.agent_status' <<<"$HOUT"
    else
        echo gone
    fi
}

transcript_path() {  # kind sid
    [ -n "$2" ] || return 0
    case "$1" in
        # A session gets its file only once its first prompt is written.
        claude) ls "$CLAUDE_HOME"/projects/*/"$2".jsonl 2>/dev/null | head -1 || true ;;
        codex)  find "$CODEX_DIR/sessions" -type f -name "*$2.jsonl" 2>/dev/null | head -1 || true ;;
    esac
}

turn_count() {  # kind file
    [ -n "$2" ] && [ -f "$2" ] || { echo 0; return; }
    case "$1" in
        claude) jq -c 'select(.type == "system" and .subtype == "turn_duration")' "$2" | wc -l | tr -d ' ' ;;
        codex)  jq -c 'select(.type == "event_msg" and .payload.type == "task_complete")' "$2" | wc -l | tr -d ' ' ;;
    esac
}

# A codex turn opens with task_started and closes with task_complete, or with
# turn_aborted when interrupted.
codex_turn_open() {  # file -> 0 while a turn is in progress
    [ -n "$1" ] && [ -f "$1" ] || return 1
    [ "$(jq -r 'select(.type == "event_msg") | .payload.type
                | select(. == "task_started" or . == "task_complete" or . == "turn_aborted")' "$1" \
         | tail -1)" = task_started ]
}

# Herdr reports a codex waiting for input as "unknown": its composer looks the
# same during a turn and after it, so no screen rule can call it idle. The
# transcript can, so settle "unknown" from there.
settled_status() {  # name -> agent_status, with a codex "unknown" resolved
    local status file
    status="$(agent_status "$1")"
    if [ "$status" = unknown ] && [ "$(state_get "$1" '.kind')" = codex ]; then
        file="$(transcript_path codex "$(agent_sid "$1")")"
        if codex_turn_open "$file"; then status=working; else status=idle; fi
    fi
    echo "$status"
}

# Final reply of the last completed turn.
#   claude: text blocks after the last user record (prompt or tool result) that
#           precedes the last turn_duration; if the turn closed without such
#           text, the last text block since the prompt.
#   codex:  last task_complete.last_agent_message.
extract_reply() {  # kind file
    case "$1" in
        claude)
            jq -rs '
                (map(.type == "system" and .subtype == "turn_duration") | rindex(true)) as $end
                | if $end == null then "" else
                    .[:$end]
                    | map(select(.isSidechain != true and (.type == "user" or .type == "assistant")))
                    | def texts: map(.message.content | if type == "array" then .[] else empty end
                                     | select(.type == "text") | .text);
                      def is_prompt: .type == "user" and .isMeta != true
                                     and ((.message.content | type) == "string"
                                          or ((.message.content | map(.type) | index("tool_result")) == null));
                      (map(.type == "user") | rindex(true)) as $u
                    | (map(is_prompt) | rindex(true)) as $p
                    | (.[($u // -1) + 1:] | texts | join("\n")) as $final
                    | if $final != "" then $final
                      else (.[($p // -1) + 1:] | texts | last // "") end
                  end
            ' "$2"
            ;;
        codex)
            jq -rs '
                map(select(.type == "event_msg" and .payload.type == "task_complete"))
                | last | .payload.last_agent_message // ""
            ' "$2"
            ;;
    esac
}

# Right after a key answers a dialog, Herdr can still report the old "blocked"
# for a moment; only call it blocked if it stays that way.
settled_unblocked() {  # name -> 0 unless still blocked after ~3s
    local i
    for i in 1 2 3 4 5 6; do
        [ "$(agent_status "$1")" = blocked ] || return 0
        sleep 0.5
    done
    return 1
}

# Mitigation, not a proven fix: twice in testing, a prompt sent right after
# startup never reached codex. Hold `up` until the screen stops changing.
wait_screen_stable() {  # name
    local prev="" cur i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        hcall agent read "$1" --source visible || return 0
        cur="$HOUT"
        [ -n "$prev" ] && [ "$cur" = "$prev" ] && return 0
        prev="$cur"
        sleep 1
    done
}

print_screen() {  # name [lines] -> stderr
    local name="$1" lines="${2:-40}" pane
    if hcall agent read "$name" --source recent-unwrapped --lines "$lines"; then :
    else
        pane="$(state_get "$name" '.pane_id')"
        hcall pane read "$pane" --source recent-unwrapped --lines "$lines" || true
    fi
    { echo "----- screen: $name (last $lines lines) -----"; printf '%s\n' "$HOUT"; echo "-----"; } >&2
}

# Record where the agent's transcript stands, so the reply printed after the
# turn can be proven to belong to that turn.
mark_baseline() {  # name
    local kind sid file count
    kind="$(state_get "$1" '.kind')"
    sid="$(agent_sid "$1")"
    file="$(transcript_path "$kind" "$sid")"
    count="$(turn_count "$kind" "$file")"
    state_set "$1" '.pending = {sid: $sid, turns: ($turns | tonumber)}' --arg sid "$sid" --arg turns "$count"
}

# Wait until the transcript shows a turn newer than the baseline, then print it.
# With a timeout it also gives up after that many ms; codex needs one, because
# Herdr cannot say when its turn ends and this loop is the only wait.
finish_reply() {  # name [out_file] [timeout_ms]
    local name="$1" out="${2:-}" timeout="${3:-}" kind base_sid base_turns sid file count deadline reply
    local give_up="" status
    kind="$(state_get "$name" '.kind')"
    base_sid="$(state_get "$name" '.pending.sid // ""')"
    base_turns="$(state_get "$name" '.pending.turns // 0')"
    deadline=$(( $(date +%s) + TRANSCRIPT_GRACE_S ))
    [ -n "$timeout" ] && give_up=$(( $(date +%s) + timeout / 1000 ))
    while :; do
        sid="$(agent_sid "$name")"
        file="$(transcript_path "$kind" "$sid")"
        count="$(turn_count "$kind" "$file")"
        if [ -n "$file" ] && { [ "$count" -gt "$base_turns" ] || { [ "$sid" != "$base_sid" ] && [ "$count" -ge 1 ]; }; }; then
            break
        fi
        [ -n "$give_up" ] && [ "$(date +%s)" -ge "$give_up" ] \
            && bail 4 "'$name' did not finish within ${timeout}ms; it may still be working -- use 'wait $name'"
        # Herdr's settled state tracks lifecycle, not turns; keep waiting while
        # the agent is still busy with this turn.
        status="$(settled_status "$name")"
        if [ "$status" = blocked ]; then
            print_screen "$name"
            bail 3 "'$name' stopped at an approval or question dialog; ask the user, answer with 'keys', then 'wait $name'"
        elif [ "$status" = working ]; then
            deadline=$(( $(date +%s) + TRANSCRIPT_GRACE_S ))
        elif [ "$(date +%s)" -ge "$deadline" ]; then
            print_screen "$name"
            bail 5 "'$name' is settled but no new turn was recorded (sid=${sid:-none}); the prompt may never have been submitted -- check the screen before resending"
        fi
        sleep 1
    done
    reply="$(extract_reply "$kind" "$file")"
    state_set "$name" 'del(.pending)'
    [ -n "$reply" ] || die "the turn completed without a text reply (transcript: $file)"
    emit_reply "$reply" "$out"
}

# One place decides whether a reply goes to stdout or to a file, so a caller
# that must keep its own context small never has to hold the text.
emit_reply() {  # text out_file
    if [ -n "$2" ]; then
        printf '%s\n' "$1" > "$2"
        printf 'wrote %s (%s lines, %s bytes)\n' "$2" "$(printf '%s\n' "$1" | wc -l | tr -d ' ')" "$(printf '%s\n' "$1" | wc -c | tr -d ' ')"
    else
        printf '%s\n' "$1"
    fi
}

# --- commands ----------------------------------------------------------------
# Model and reasoning-level choices, summarised. The point is to answer without
# pouring a model catalogue or a help page into the caller's context.
cmd_models() {
    local kind="${1:-}"
    case "$kind" in ""|claude|codex) ;; *) usage_error "models takes claude or codex" ;; esac
    if [ -z "$kind" ] || [ "$kind" = claude ]; then
        local aliases levels default
        aliases="$(claude --help 2>/dev/null | sed -n "/--model <model>/,/^  -/p" | grep -oE "'[a-z0-9.-]+'" | tr -d "'" | paste -sd, - || true)"
        levels="$(claude --help 2>/dev/null | sed -n "/--effort <level>/,/^  --/p" | grep -oE '\(([a-z]+, )+[a-z]+\)' | tr -d '()' || true)"
        default="$(jq -r '.model // empty' "$CLAUDE_HOME/settings.json" 2>/dev/null || true)"
        echo "claude  models: ${aliases:-see claude --help} (aliases; full names also work)"
        echo "claude  effort: ${levels:-see claude --help}"
        echo "claude  default model: ${default:-whatever the CLI is configured with}"
    fi
    if [ -z "$kind" ] || [ "$kind" = codex ]; then
        local catalogue
        catalogue="$(codex debug models 2>/dev/null | jq -r '.models[] | select(.visibility == "list")
            | "codex   \(.slug): levels \([.supported_reasoning_levels[].effort] | join(",")) (default \(.default_reasoning_level))"' 2>/dev/null || true)"
        if [ -n "$catalogue" ]; then printf '%s\n' "$catalogue"; else echo "codex   models: could not read the catalogue"; fi
        local cmodel ceffort
        cmodel="$(grep -E '^model *=' "$CODEX_DIR/config.toml" 2>/dev/null | head -1 | sed 's/.*= *//; s/"//g' || true)"
        ceffort="$(grep -E '^model_reasoning_effort *=' "$CODEX_DIR/config.toml" 2>/dev/null | head -1 | sed 's/.*= *//; s/"//g' || true)"
        echo "codex   defaults: ${cmodel:-cli default} ${ceffort:-}"
        echo "codex   reasoning level is passed as: -c model_reasoning_effort=<level>"
    fi
}

cmd_up() {
    local name="" kind="" cwd="$PWD" direction="" agent_args=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --kind) kind="${2:-}"; shift 2 ;;
            --cwd) cwd="${2:-}"; shift 2 ;;
            --direction) direction="${2:-}"; shift 2 ;;
            --) shift; agent_args=("$@"); break ;;
            -*) usage_error "unknown option for up: $1" ;;
            *) [ -z "$name" ] || usage_error "unexpected argument: $1"; name="$1"; shift ;;
        esac
    done
    [ -n "$name" ] || usage_error "up needs a name"
    [[ "$name" =~ $NAME_RE ]] || usage_error "invalid name: $name (must match $NAME_RE)"
    case "$kind" in claude|codex) ;; *) usage_error "--kind must be claude or codex" ;; esac
    case "$direction" in ""|right|down) ;; *) usage_error "--direction must be right or down" ;; esac
    [ -d "$cwd" ] || die "cwd does not exist: $cwd"
    cwd="$(cd "$cwd" && pwd)"
    # A shared codex app-server daemon runs hooks with the environment of the
    # pane that first started it, so the session id is reported to that pane
    # and orch cannot find the transcript. A pane-local codex reports it here.
    if [ "$kind" = codex ]; then
        case " ${agent_args[*]:-} " in
            *" --no-daemon "*) ;;
            *) agent_args=(--no-daemon ${agent_args[@]+"${agent_args[@]}"}) ;;
        esac
    fi

    local sf; sf="$(state_file "$name")"
    if [ -f "$sf" ]; then
        if pane_alive "$(jq -r '.pane_id' "$sf")"; then
            die "'$name' is already running (pane $(jq -r '.pane_id' "$sf")); use another name or 'down' it first"
        fi
        rm -f "$sf"
    fi
    if hcall agent get "$name"; then
        die "a live Herdr agent is already named '$name'"
    fi

    # Placement: the first agent splits the calling pane (right when it is at
    # least twice as wide as tall, else down); later ones stack under the
    # newest orch pane so columns do not keep halving.
    local anchor="" newest=0 n f created p
    for n in $(managed_names); do
        f="$(state_file "$n")"
        p="$(jq -r '.pane_id' "$f")"
        created="$(jq -r '.created_at' "$f")"
        if pane_alive "$p" && [ "$created" -ge "$newest" ]; then
            anchor="$p"; newest="$created"
        fi
    done
    if [ -z "$anchor" ]; then
        anchor="$HERDR_PANE_ID"
        if [ -z "$direction" ]; then
            hcall pane layout --pane "$anchor" || die "pane layout failed: $(herr_msg)"
            local w h
            w="$(jq -r --arg p "$anchor" '.result.layout.panes[] | select(.pane_id == $p) | .rect.width' <<<"$HOUT")"
            h="$(jq -r --arg p "$anchor" '.result.layout.panes[] | select(.pane_id == $p) | .rect.height' <<<"$HOUT")"
            if [ -n "$w" ] && [ -n "$h" ] && [ "$w" -ge $(( h * 2 )) ]; then direction=right; else direction=down; fi
        fi
    fi
    [ -n "$direction" ] || direction=down

    hcall pane split --pane "$anchor" --direction "$direction" --cwd "$cwd" --no-focus \
        || die "pane split failed: $(herr_msg)"
    local pane; pane="$(jq -r '.result.pane.pane_id' <<<"$HOUT")"

    mkdir -p "$(state_dir)"
    jq -n --arg name "$name" --arg kind "$kind" --arg pane "$pane" --arg cwd "$cwd" \
          --arg owner "${ORCH_OWNER:-$HERDR_PANE_ID}" --argjson created "$(date +%s)" \
          '{name: $name, kind: $kind, pane_id: $pane, cwd: $cwd, owner_pane: $owner, created_at: $created}' > "$sf"

    local rc=0
    if [ ${#agent_args[@]} -gt 0 ]; then
        hcall agent start "$name" --kind "$kind" --pane "$pane" --timeout "$START_TIMEOUT_MS" -- "${agent_args[@]}" || rc=$?
    else
        hcall agent start "$name" --kind "$kind" --pane "$pane" --timeout "$START_TIMEOUT_MS" || rc=$?
    fi
    if [ "$rc" -ne 0 ]; then
        if [ "$(herr_code)" = agent_not_ready ]; then
            # Startup dialogs are often transient; give them a moment to clear.
            local i status=""
            for i in 1 2 3 4 5 6 7 8 9 10; do
                status="$(settled_status "$name")"
                case "$status" in idle|done) break ;; esac
                sleep 1
            done
            case "$status" in
                idle|done) ;;
                *) print_screen "$name"
                   bail 3 "'$name' (pane $pane) is $status during startup; inspect the screen above and ask the user before answering it" ;;
            esac
        else
            local msg; msg="$(herr_msg)"
            print_screen "$name"
            die "agent start failed in pane $pane: $msg (the pane is recorded; 'down $name' removes it)"
        fi
    fi
    wait_screen_stable "$name"
    printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$kind" "$pane" "$(settled_status "$name")" "$cwd"
}

# A pane the user takes over: started, handed its brief, then forgotten. It is
# deliberately not recorded, so `status` never lists it and `down` never closes
# it -- its life is the user's to end.
cmd_handoff() {
    local name="" kind="" cwd="$PWD" direction="" brief="" prompt="" agent_args=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --kind) kind="${2:-}"; shift 2 ;;
            --cwd) cwd="${2:-}"; shift 2 ;;
            --direction) direction="${2:-}"; shift 2 ;;
            --brief) brief="${2:-}"; shift 2 ;;
            --prompt) prompt="${2:-}"; shift 2 ;;
            --) shift; agent_args=("$@"); break ;;
            -*) usage_error "unknown option for handoff: $1" ;;
            *) [ -z "$name" ] || usage_error "unexpected argument: $1"; name="$1"; shift ;;
        esac
    done
    [ -n "$name" ] || usage_error "handoff needs a name"
    [ -z "$brief" ] || [ -z "$prompt" ] || usage_error "pass --brief or --prompt, not both"
    [ -n "$brief" ] && { [ -f "$brief" ] || die "brief file not found: $brief"; brief="$(cd "$(dirname "$brief")" && pwd)/$(basename "$brief")"; }

    # Start it exactly as `up` does, then take it off the books.
    local out
    if [ ${#agent_args[@]} -gt 0 ]; then
        out="$(cmd_up "$name" --kind "$kind" ${cwd:+--cwd "$cwd"} ${direction:+--direction "$direction"} -- "${agent_args[@]}")"
    else
        out="$(cmd_up "$name" --kind "$kind" ${cwd:+--cwd "$cwd"} ${direction:+--direction "$direction"})"
    fi
    local pane; pane="$(printf '%s' "$out" | cut -f3)"

    local text=""
    [ -n "$brief" ] && text="Read $brief and carry out what it asks. It is the whole brief; ask me if anything in it is unclear."
    [ -n "$prompt" ] && text="$prompt"
    if [ -n "$text" ]; then
        if ! hcall agent prompt "$name" "$text" --wait --until working --timeout 20000; then
            case "$(herr_code)" in
                agent_blocked|agent_prompt_stalled)
                    print_screen "$name"
                    rm -f "$(state_file "$name")"
                    bail 5 "'$name' is running in pane $pane but did not take the brief; it is now independent, so hand the pane to the user as is" ;;
                *) : ;;   # it may already have finished a short turn
            esac
        fi
    fi

    rm -f "$(state_file "$name")"
    printf '%s\t%s\t%s\t%s\n' "$name" "$kind" "$pane" "$cwd"
    echo "handed off: independent of orch -- not listed by status, never closed by down" >&2
}

cmd_ask() {
    local name="" text="" have_text=0 timeout="$DEFAULT_ASK_TIMEOUT_MS" out=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --timeout) timeout="${2:-}"; shift 2 ;;
            --out) out="${2:-}"; shift 2 ;;
            *)
                if [ -z "$name" ]; then name="$1"
                elif [ "$have_text" -eq 0 ]; then text="$1"; have_text=1
                else usage_error "unexpected argument: $1"; fi
                shift ;;
        esac
    done
    [ -n "$name" ] && [ "$have_text" -eq 1 ] || usage_error "ask needs a name and a prompt"
    require_managed "$name"
    [ "$text" = "-" ] && text="$(cat)"
    [ -n "$text" ] || usage_error "prompt is empty"

    local status; status="$(settled_status "$name")"
    case "$status" in
        idle|done) ;;
        working) bail 6 "'$name' is still working on a previous turn; use 'wait $name' first" ;;
        blocked) print_screen "$name"; bail 3 "'$name' is waiting at an approval or question dialog" ;;
        gone) die "'$name' is no longer running in pane $(state_get "$name" '.pane_id')" ;;
        *) print_screen "$name"; die "'$name' is in state '$status'; not sending" ;;
    esac

    mark_baseline "$name"
    local kind rc=0; kind="$(state_get "$name" '.kind')"
    if [ "$kind" = codex ]; then
        # Herdr never sees a codex turn end, so only confirm it started;
        # finish_reply watches the transcript for the end.
        hcall agent prompt "$name" "$text" --wait --until working --until blocked --timeout 20000 || rc=$?
    else
        hcall agent prompt "$name" "$text" --wait --timeout "$timeout" || rc=$?
    fi
    if [ "$rc" -ne 0 ]; then
        case "$(herr_code)" in
            agent_prompt_stalled)
                print_screen "$name"
                bail 5 "prompt was written but '$name' showed no activity; check the screen before resending (it may not have been submitted)" ;;
            timeout)
                if [ "$kind" = codex ]; then
                    print_screen "$name"
                    bail 5 "'$name' did not start on the prompt; check the screen before resending"
                fi
                bail 4 "'$name' did not finish within ${timeout}ms; it may still be working -- use 'wait $name'" ;;
            agent_blocked)
                print_screen "$name"; bail 3 "'$name' is waiting at an approval or question dialog" ;;
            *) die "agent prompt failed: $(herr_msg)" ;;
        esac
    fi
    status="$(jq -r '.result.agent.agent_status // empty' <<<"$HOUT")"
    if [ "$status" = blocked ]; then
        print_screen "$name"
        bail 3 "'$name' stopped at an approval or question dialog; ask the user, answer with 'keys', then 'wait $name'"
    fi
    finish_reply "$name" "$out" "$timeout"
}

# Hand a tracked agent a prompt and return at once, so the caller keeps working.
# The reply is collected later with `wait` (or `reply`).
cmd_send() {
    local name="" text="" have_text=0
    while [ $# -gt 0 ]; do
        case "$1" in
            -*) usage_error "unknown option for send: $1" ;;
            *)
                if [ -z "$name" ]; then name="$1"
                elif [ "$have_text" -eq 0 ]; then text="$1"; have_text=1
                else usage_error "unexpected argument: $1"; fi
                shift ;;
        esac
    done
    [ -n "$name" ] && [ "$have_text" -eq 1 ] || usage_error "send needs a name and a prompt"
    require_managed "$name"
    [ "$text" = "-" ] && text="$(cat)"
    [ -n "$text" ] || usage_error "prompt is empty"

    local status; status="$(settled_status "$name")"
    case "$status" in
        idle|done) ;;
        working) bail 6 "'$name' is still working on a previous turn; collect it with 'wait $name' first" ;;
        blocked) print_screen "$name"; bail 3 "'$name' is waiting at an approval or question dialog" ;;
        gone) die "'$name' is no longer running in pane $(state_get "$name" '.pane_id')" ;;
        *) print_screen "$name"; die "'$name' is in state '$status'; not sending" ;;
    esac

    mark_baseline "$name"
    # Returns as soon as the agent starts the turn; the turn itself runs on.
    if ! hcall agent prompt "$name" "$text" --wait --until working --timeout 20000; then
        case "$(herr_code)" in
            agent_prompt_stalled|timeout)
                print_screen "$name"
                bail 5 "'$name' did not start on the prompt; check the screen before resending" ;;
            agent_blocked)
                print_screen "$name"; bail 3 "'$name' is waiting at an approval or question dialog" ;;
            *) die "agent prompt failed: $(herr_msg)" ;;
        esac
    fi
    echo "sent to $name; collect with: wait $name [--out FILE]"
}

cmd_wait() {
    local name="" timeout="" out=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --timeout) timeout="${2:-}"; shift 2 ;;
            --out) out="${2:-}"; shift 2 ;;
            *) [ -z "$name" ] || usage_error "unexpected argument: $1"; name="$1"; shift ;;
        esac
    done
    [ -n "$name" ] || usage_error "wait needs a name"
    require_managed "$name"
    if [ "$(state_get "$name" '.pending != null')" != true ]; then
        case "$(settled_status "$name")" in
            idle|done) die "nothing in progress for '$name'; use 'reply $name' for its last answer" ;;
        esac
        mark_baseline "$name"
    fi

    # Herdr never sees a codex turn end, so for codex finish_reply is the wait.
    if [ "$(state_get "$name" '.kind')" != codex ]; then
        local rc=0
        if [ -n "$timeout" ]; then hcall agent wait "$name" --timeout "$timeout" || rc=$?
        else hcall agent wait "$name" || rc=$?; fi
        if [ "$rc" -ne 0 ]; then
            [ "$(herr_code)" = timeout ] && bail 4 "'$name' is still not settled after ${timeout}ms"
            die "agent wait failed: $(herr_msg)"
        fi
    fi
    if ! settled_unblocked "$name"; then
        print_screen "$name"
        bail 3 "'$name' is waiting at an approval or question dialog"
    fi
    finish_reply "$name" "$out" "$timeout"
}

cmd_reply() {
    local name="" out=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --out) out="${2:-}"; shift 2 ;;
            *) [ -z "$name" ] || usage_error "unexpected argument: $1"; name="$1"; shift ;;
        esac
    done
    [ -n "$name" ] || usage_error "reply needs a name"
    set -- "$name"
    require_managed "$1"
    local kind sid file reply
    kind="$(state_get "$1" '.kind')"
    sid="$(agent_sid "$1")"
    [ -n "$sid" ] || die "'$1' has no session yet (codex reports one only after its first turn)"
    file="$(transcript_path "$kind" "$sid")"
    [ -n "$file" ] || die "transcript for session $sid not found"
    reply="$(extract_reply "$kind" "$file")"
    [ -n "$reply" ] || die "no completed turn with a text reply in $file"
    emit_reply "$reply" "$out"
}

cmd_screen() {
    local name="" lines=80
    while [ $# -gt 0 ]; do
        case "$1" in
            --lines) lines="${2:-}"; shift 2 ;;
            *) [ -z "$name" ] || usage_error "unexpected argument: $1"; name="$1"; shift ;;
        esac
    done
    [ -n "$name" ] || usage_error "screen needs a name"
    require_managed "$name"
    print_screen "$name" "$lines" 2>&1
}

cmd_keys() {
    [ $# -ge 2 ] || usage_error "keys needs a name and at least one key"
    local name="$1"; shift
    require_managed "$name"
    hcall agent send-keys "$name" "$@" || die "send-keys failed: $(herr_msg)"
    echo "sent: $*"
}

cmd_status() {
    local names n f pane status
    if [ $# -gt 0 ]; then names="$*"; else names="$(managed_names)"; fi
    [ -n "$names" ] || { echo "no agents started by orch from this pane"; return 0; }
    printf 'NAME\tKIND\tPANE\tSTATUS\tREPLY\tCWD\n'
    local kind reply sid file count base
    for n in $names; do
        require_managed "$n"
        f="$(state_file "$n")"
        pane="$(jq -r '.pane_id' "$f")"
        kind="$(jq -r '.kind' "$f")"
        if pane_alive "$pane"; then status="$(settled_status "$n")"; [ "$status" = gone ] && status="exited(pane open)"
        else status="pane-closed"; fi
        reply="-"
        if [ "$(jq -r '.pending != null' "$f")" = true ]; then
            base="$(jq -r '.pending.turns // 0' "$f")"
            sid="$(agent_sid "$n")"
            file="$(transcript_path "$kind" "$sid")"
            count="$(turn_count "$kind" "$file")"
            if [ "$count" -gt "$base" ]; then reply="ready"; else reply="waiting"; fi
        fi
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$n" "$kind" "$pane" "$status" "$reply" "$(jq -r '.cwd' "$f")"
    done
}

cmd_down() {
    local names="" all=0 n
    while [ $# -gt 0 ]; do
        case "$1" in
            --all) all=1; shift ;;
            -*) usage_error "unknown option for down: $1" ;;
            *) names="$names $1"; shift ;;
        esac
    done
    if [ "$all" -eq 1 ]; then names="$(managed_names)"; fi
    [ -n "${names// /}" ] || { [ "$all" -eq 1 ] && { echo "nothing to stop"; return 0; }; usage_error "down needs names or --all"; }
    for n in $names; do require_managed "$n"; done

    local f pane status i
    for n in $names; do
        f="$(state_file "$n")"
        pane="$(jq -r '.pane_id' "$f")"
        if ! pane_alive "$pane"; then
            rm -f "$f"; echo "$n: pane $pane already closed"; continue
        fi
        status="$(agent_status "$n")"
        if [ "$status" != gone ]; then
            # Exit the agent before its pane goes away: codex quits on the first
            # ctrl+c, claude on the second.
            for i in 1 2 3 4 5 6; do
                [ "$(agent_status "$n")" = gone ] && break
                case "$i" in 1|3|5) hcall agent send-keys "$n" ctrl+c || true ;; esac
                sleep 0.5
            done
        fi
        if pane_alive "$pane"; then
            hcall pane close "$pane" || die "failed to close pane $pane: $(herr_msg)"
        fi
        rm -f "$f"
        echo "$n: stopped (was $status), pane $pane closed"
    done
}

main() {
    [ $# -gt 0 ] || { usage >&2; exit 2; }
    local cmd="$1"; shift
    case "$cmd" in
        -h|--help|help) usage; exit 0 ;;
    esac
    require_env
    case "$cmd" in
        up) cmd_up "$@" ;;
        handoff) cmd_handoff "$@" ;;
        ask) cmd_ask "$@" ;;
        send) cmd_send "$@" ;;
        wait) cmd_wait "$@" ;;
        reply) cmd_reply "$@" ;;
        screen) cmd_screen "$@" ;;
        keys) cmd_keys "$@" ;;
        status) cmd_status "$@" ;;
        models) cmd_models "$@" ;;
        down) cmd_down "$@" ;;
        *) usage_error "unknown command: $cmd" ;;
    esac
}

main "$@"
