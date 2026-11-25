#!/usr/bin/env bash
# Claude Code status line

set -f

usage_dir="${CLAUDE_USAGE_DIR:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/usage}"

# budget subcommand: bash statusline-command.sh budget <new_budget>
# Updates the budget= line in .config.
if [ "${1:-}" = "budget" ] && [ -n "${2:-}" ]; then
    [ ! -f "$usage_dir/.config" ] && echo "no config at $usage_dir/.config" && exit 1
    sed -i '' "s/^budget=.*/budget=$2/" "$usage_dir/.config"
    cat "$usage_dir/.config"
    exit 0
fi

# usage subcommand: bash statusline-command.sh usage <initial_usage>
# Directly overwrites initial_usage= in .config (no offset files written).
if [ "${1:-}" = "usage" ] && [ -n "${2:-}" ]; then
    [ ! -f "$usage_dir/.config" ] && echo "no config at $usage_dir/.config" && exit 1
    sed -i '' "s/^initial_usage=.*/initial_usage=$2/" "$usage_dir/.config"
    cat "$usage_dir/.config"
    exit 0
fi

# sync subcommand: bash statusline-command.sh sync <real_usage>
# Writes a negative offset for each session so continuing sessions only
# count the delta. Dead sessions cancel out (cost + -cost = 0).
# start_ts=0 disables timestamp filtering — offsets handle the math.
if [ "${1:-}" = "sync" ] && [ -n "${2:-}" ]; then
    [ ! -f "$usage_dir/.config" ] && echo "no config at $usage_dir/.config" && exit 1
    set +f
    for f in "$usage_dir"/*; do
        [ ! -f "$f" ] && continue
        base=$(basename "$f")
        case "$base" in .* | *_offset) continue ;; esac
        cost=$(awk -F'\t' '{print $2}' "$f")
        [ -n "$cost" ] && printf '%s\t-%s\toffset\t0\t0\t0\n' "$(date +%s)" "$cost" > "${f}_offset"
    done
    set -f
    sed -i '' "s/^initial_usage=.*/initial_usage=$2/; s/^start_ts=.*/start_ts=0/" "$usage_dir/.config"
    cat "$usage_dir/.config"
    exit 0
fi

# fetch-refresh subcommand: bash statusline-command.sh fetch-refresh <repo_root>
# Background `git fetch` so unpushed/unpulled counts stay current.
# Runs detached from the render; failures are silent.
if [ "${1:-}" = "fetch-refresh" ] && [ -n "${2:-}" ]; then
    root="$2"
    [ -d "$root/local" ] || exit 0
    git -C "$root" --no-optional-locks fetch --quiet 2>/dev/null
    exit 0
fi

input=$(cat)
[ -z "$input" ] && printf "Claude" && exit 0

# ===== Colors =====
blue='\033[38;2;97;175;239m'
amber='\033[38;2;229;192;123m'
cyan='\033[38;2;86;182;194m'
green='\033[38;2;80;200;120m'
orange='\033[38;2;255;176;85m'
yellow='\033[38;2;230;200;0m'
red='\033[38;2;235;87;87m'
magenta='\033[38;2;198;120;221m'
dim='\033[2m'
reset='\033[0m'

sep=" ${dim}│${reset} "

# ===== Helpers =====

fmt_time() {
    local m="$1"
    [ -z "$m" ] && return
    if [ "$m" -ge 1440 ]; then
        echo "$((m / 1440))d$(( (m % 1440) / 60 ))h$((m % 60))m"
    elif [ "$m" -ge 60 ]; then
        echo "$((m / 60))h$((m % 60))m"
    else
        echo "${m}m"
    fi
}

add()  { [ -z "$out" ]   && out+="$1"   || out+="${sep}$1"; }
addu() { [ -z "$usage" ] && usage+="$1" || usage+="${sep}$1"; }

# ===== Extract data =====
model=$(echo "$input" | jq -r '.model.display_name // empty')
cwd=$(echo "$input"   | jq -r '.workspace.current_dir // .cwd // empty')
used=$(echo "$input"  | jq -r '.context_window.used_percentage // empty')

# "Claude Opus 4.6 (1M context)" → "Opus 4.6 (1M)"
model="${model#Claude }"
model="${model/ context/}"

branch=""
[ -n "$cwd" ] && branch=$(git -C "$cwd" --no-optional-locks symbolic-ref --short HEAD 2>/dev/null)

now=$(date +%s)
rl_five=$(echo "$input"      | jq -r '.rate_limits.five_hour.used_percentage // empty')
rl_seven=$(echo "$input"     | jq -r '.rate_limits.seven_day.used_percentage // empty')
rl_resets_5h=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
rl_resets_7d=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')

cost_usd=$(echo "$input"       | jq -r '.cost.total_cost_usd // empty')
duration_ms=$(echo "$input"    | jq -r '.cost.total_duration_ms // empty')
api_duration_ms=$(echo "$input"| jq -r '.cost.total_api_duration_ms // empty')
lines_added=$(echo "$input"    | jq -r '.cost.total_lines_added // empty')
lines_removed=$(echo "$input"  | jq -r '.cost.total_lines_removed // empty')
session_id=$(echo "$input"     | jq -r '.session_id // empty')
transcript_path=$(echo "$input"| jq -r '.transcript_path // empty')
transcript_file="${transcript_path##*/}"
transcript_file="${transcript_file%.jsonl}"
effort_level=$(echo "$input"   | jq -r '.effort.level // empty')
agent_name=$(echo "$input"     | jq -r '.agent.name // empty')
total_input=$(echo "$input"    | jq -r '.context_window.total_input_tokens // empty')
total_output=$(echo "$input"   | jq -r '.context_window.total_output_tokens // empty')
cache_read=$(echo "$input"     | jq -r '.context_window.current_usage.cache_read_input_tokens // empty')
cache_create=$(echo "$input"   | jq -r '.context_window.current_usage.cache_creation_input_tokens // empty')

# ===== Background git fetch =====
# Keeps unpushed/unpulled counts current. Debounced per branch via a lock
# file so frequent renders don't spawn a fetch every time — at most every
# 10 min, restricted to repos with a local/ dir.
if [ -n "$branch" ] && [ -n "$cwd" ]; then
    repo_root=$(git -C "$cwd" --no-optional-locks rev-parse --show-toplevel 2>/dev/null)
    if [ -n "$repo_root" ] && [ -d "$repo_root/local" ]; then
        fetch_lock="$repo_root/local/.fetch-lock"
        last=$(awk -F'\t' -v b="$branch" '$1==b {print $2; exit}' "$fetch_lock" 2>/dev/null)
        if [ -z "$last" ] || [ $(( now - last )) -gt 600 ]; then
            # Stamp the attempt first (debounce even if the fetch fails), then detach.
            if tmp_lock=$(mktemp "${fetch_lock}.XXXXXX" 2>/dev/null); then
                [ -f "$fetch_lock" ] && awk -F'\t' -v b="$branch" '$1!=b' "$fetch_lock" > "$tmp_lock"
                printf '%s\t%s\n' "$branch" "$now" >> "$tmp_lock"
                mv "$tmp_lock" "$fetch_lock"
            fi
            ( bash "$0" fetch-refresh "$repo_root" >/dev/null 2>&1 & )
        fi
    fi
fi

# ===== Usage tracking =====
today=$(date +%Y-%m-%d)
daily_total=""

if [ -n "$session_id" ] && [ -n "$cost_usd" ] && [ -z "$rl_five" ] && [ -z "$rl_seven" ]; then
    mkdir -p "$usage_dir"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$now" "$cost_usd" "${model:-unknown}" \
        "${api_duration_ms:-0}" "${lines_added:-0}" "${lines_removed:-0}" \
        > "$usage_dir/$session_id"
fi

# Load config: budget, initial_usage, start_ts (epoch)
budget="" initial_usage="" start_ts=""
[ -f "$usage_dir/.config" ] && . "$usage_dir/.config" 2>/dev/null
period_total=""
if [ -n "$budget" ] && [ -n "$start_ts" ]; then
    set +f
    tracked=$(awk -v t="$start_ts" -F'\t' '($1+0) >= (t+0) {s += $2} END {printf "%.2f", s}' "$usage_dir"/* 2>/dev/null)
    set -f
    period_total=$(echo "scale=2; ${initial_usage:-0} + ${tracked:-0}" | bc 2>/dev/null)
fi

# ===== Assemble =====
out=""
usage=""

# Model — amber for Opus, cyan for Haiku, blue otherwise
if [ -n "$model" ]; then
    model_color="$blue"
    case "$model" in *Opus*)  model_color="$amber" ;; *Haiku*) model_color="$cyan" ;; esac
    add "${model_color}${model}${reset}"
fi

# Effort level
if [ -n "$effort_level" ]; then
    case "$effort_level" in
        low)    effort_color="$dim" ;;
        medium) effort_color="$cyan" ;;
        high)   effort_color="$orange" ;;
        xhigh)  effort_color="$red" ;;
        max)    effort_color="$red" ;;
        *)      effort_color="$dim" ;;
    esac
    add "${effort_color}${effort_level}${reset}"
fi

# Agent name
[ -n "$agent_name" ] && add "${dim}agent:${reset}${cyan}${agent_name}${reset}"

# Context window %
if [ -n "$used" ]; then
    ctx_pct=$(printf "%.0f" "$used")
    if   [ "$ctx_pct" -ge 80 ]; then ctx_color="$red"
    elif [ "$ctx_pct" -ge 50 ]; then ctx_color="$orange"
    else ctx_color="$cyan"; fi
    add "${dim}ctx${reset} ${ctx_color}${ctx_pct}%${reset}"
fi

# Pending ScheduleWakeup (shadowed by hooks/wakeup-marker.sh)
wakeup_file="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/next-wakeup"
wakeup_reason=""
if [ -f "$wakeup_file" ]; then
    wakeup_line=$(head -n1 "$wakeup_file" 2>/dev/null)
    wakeup_ts="${wakeup_line%%	*}"
    wakeup_reason="${wakeup_line#*	}"
    if [ -n "$wakeup_ts" ] && [ "$wakeup_ts" -gt "$now" ] 2>/dev/null; then
        secs_left=$(( wakeup_ts - now ))
        if [ "$secs_left" -lt 60 ]; then wake_fmt="${secs_left}s"
        elif [ "$secs_left" -lt 3600 ]; then wake_fmt="$((secs_left/60))m$((secs_left%60))s"
        else wake_fmt="$((secs_left/3600))h$(( (secs_left%3600)/60 ))m"
        fi
        add "${yellow}⏰ ${wake_fmt}${reset}"
    else
        wakeup_reason=""
        rm -f "$wakeup_file" 2>/dev/null
    fi
fi

# Git branch + dirty state
if [ -n "$branch" ]; then
    git_str="${magenta}${branch}${reset}"
    porcelain=$(git -C "$cwd" --no-optional-locks status --porcelain 2>/dev/null)
    if [ -z "$porcelain" ]; then
        git_str+=" ${green}${dim}✓${reset}"
    else
        staged=$(  printf '%s\n' "$porcelain" | awk '/^[MADRC]/'        | wc -l | tr -d ' ')
        modified=$(printf '%s\n' "$porcelain" | awk '/^.[MD]/'          | wc -l | tr -d ' ')
        untracked=$(printf '%s\n' "$porcelain" | awk '/^\?\?/'          | wc -l | tr -d ' ')
        [ "$staged"    -gt 0 ] && git_str+=" ${green}+${staged}${reset}"
        [ "$modified"  -gt 0 ] && git_str+=" ${yellow}~${modified}${reset}"
        [ "$untracked" -gt 0 ] && git_str+=" ${dim}?${untracked}${reset}"
    fi
    unpushed=$(git -C "$cwd" --no-optional-locks rev-list --count @{u}..HEAD 2>/dev/null)
    [ -n "$unpushed" ] && [ "$unpushed" -gt 0 ] && git_str+=" ${orange}⇡${unpushed}${reset}"
    unpulled=$(git -C "$cwd" --no-optional-locks rev-list --count HEAD..@{u} 2>/dev/null)
    [ -n "$unpulled" ] && [ "$unpulled" -gt 0 ] && git_str+=" ${cyan}⇣${unpulled}${reset}"
    add "$git_str"
fi

# Rate limits — 5h
if [ -n "$rl_five" ]; then
    f=$(printf "%.0f" "$rl_five")
    if   [ "$f" -ge 80 ]; then pct_color="$red"
    elif [ "$f" -ge 50 ]; then pct_color="$yellow"
    else pct_color="$cyan"; fi

    t5=""
    [ -n "$rl_resets_5h" ] && [ "$rl_resets_5h" -gt "$now" ] 2>/dev/null && \
        t5=$(fmt_time $(( (rl_resets_5h - now) / 60 )))

    if [ -n "$t5" ]; then
        addu "${dim}5h${reset} ${pct_color}${t5}:${f}%${reset}"
    else
        addu "${dim}5h${reset} ${pct_color}${f}%${reset}"
    fi
fi

# Rate limits — 7d
if [ -n "$rl_seven" ]; then
    s=$(printf "%.0f" "$rl_seven")
    t7=""
    [ -n "$rl_resets_7d" ] && [ "$rl_resets_7d" -gt "$now" ] 2>/dev/null && \
        t7=$(fmt_time $(( (rl_resets_7d - now) / 60 )))

    if [ -n "$t7" ]; then
        addu "${dim}wk${reset} ${cyan}${t7}:${s}%${reset}"
    else
        addu "${dim}wk${reset} ${cyan}${s}%${reset}"
    fi
fi

# Fable weekly limit — from local cache, shown alongside rate limits
if [ -n "$rl_five" ] || [ -n "$rl_seven" ]; then
    fable_cfg="${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json"
    fable_row=$(jq -r '
        .cachedUsageUtilization as $c
        | ($c.utilization.limits // [])[]
        | select(.kind == "weekly_scoped" and (.scope.model.display_name // "") == "Fable")
        | "\(.percent)\t\(.resets_at)\t\($c.fetchedAtMs)"
    ' "$fable_cfg" 2>/dev/null | head -n1)

    fable_pct=$(echo "$fable_row"          | awk -F'\t' '{print $1}' 2>/dev/null)
    fable_resets=$(echo "$fable_row"       | awk -F'\t' '{print $2}' 2>/dev/null)
    fable_fetched_ms=$(echo "$fable_row"   | awk -F'\t' '{print $3}' 2>/dev/null)

    if [ -n "$fable_pct" ]; then
        f_used=$(printf "%.0f" "$fable_pct" 2>/dev/null)
        if [ -n "$f_used" ]; then
            if   [ "$f_used" -ge 80 ]; then fable_color="$red"
            elif [ "$f_used" -ge 50 ]; then fable_color="$yellow"
            else fable_color="$cyan"; fi

            # resets_at is null until the weekly window actually opens, so
            # only a parsed timestamp in the past means a rolled-over window.
            fable_reset="" fable_expired=""
            if [ -n "$fable_resets" ] && [ "$fable_resets" != "null" ]; then
                fable_iso="${fable_resets%%.*}"
                fable_reset=$(date -j -u -f "%Y-%m-%dT%H:%M:%S" "$fable_iso" +%s 2>/dev/null)
                [ -n "$fable_reset" ] && [ "$fable_reset" -le "$now" ] 2>/dev/null && fable_expired=1
            fi

            # Skip once the cached window has rolled over — the percentage
            # no longer describes the current week.
            if [ -z "$fable_expired" ]; then
                tf=""
                [ -n "$fable_reset" ] && \
                    tf=$(fmt_time $(( (fable_reset - now) / 60 )))
                if [ -n "$tf" ]; then
                    fable_str="${dim}fable${reset} ${fable_color}${tf}:${f_used}%${reset}"
                else
                    fable_str="${dim}fable${reset} ${fable_color}${f_used}%${reset}"
                fi

                # Cache freshness — flag stale data older than 1h
                if [ -n "$fable_fetched_ms" ]; then
                    fable_fetched_s=$(( fable_fetched_ms / 1000 ))
                    fable_age_s=$(( now - fable_fetched_s ))
                    if [ "$fable_age_s" -gt 3600 ] 2>/dev/null; then
                        fable_age_fmt=$(fmt_time $(( fable_age_s / 60 )))
                        fable_str+=" ${dim}(${fable_age_fmt})${reset}"
                    fi
                fi

                addu "$fable_str"
            fi
        fi
    fi
fi

# API cost fallback — shown when no rate_limits (enterprise/API billing)
if [ -z "$rl_five" ] && [ -z "$rl_seven" ] && [ -n "$cost_usd" ]; then
    cost_fmt=$(printf "$%.2f" "$cost_usd")

    # Active burn rate (cost / api hours, not wall hours)
    active_rate=""
    if [ -n "$api_duration_ms" ] && [ "$api_duration_ms" -gt 0 ] 2>/dev/null; then
        active_rate=$(echo "scale=2; $cost_usd / ($api_duration_ms / 3600000)" | bc 2>/dev/null)
    fi

    cost_str="${green}${cost_fmt}${reset}"
    [ -n "$active_rate" ] && cost_str+=" ${dim}${active_rate}/hr${reset}"

    # Cache hit rate — cache_read / (cache_read + cache_create)
    cache_total=$(( ${cache_read:-0} + ${cache_create:-0} ))
    if [ "$cache_total" -gt 0 ] 2>/dev/null; then
        hit_pct=$(( cache_read * 100 / cache_total ))
        if   [ "$hit_pct" -ge 80 ]; then cache_color="$green"
        elif [ "$hit_pct" -ge 50 ]; then cache_color="$cyan"
        else cache_color="$orange"; fi
        addu "${cost_str}${sep}${dim}cache${reset} ${cache_color}${hit_pct}%${reset}"
        cost_str=""
    fi

    [ -n "$cost_str" ] && addu "$cost_str"

    # Cost per 1k tokens + net lines
    total_tokens=$(( ${total_input:-0} + ${total_output:-0} ))
    if [ "$total_tokens" -gt 0 ] 2>/dev/null; then
        cpk=$(echo "scale=2; $cost_usd * 1000 / $total_tokens" | bc 2>/dev/null)
        tok_str=""
        [ -n "$cpk" ] && tok_str="${dim}\$${cpk}/kt${reset}"
        net_lines=$(( ${lines_added:-0} - ${lines_removed:-0} ))
        if [ "$net_lines" -ge 0 ]; then
            net_str="${green}+${net_lines}${reset}"
        else
            net_str="${red}${net_lines}${reset}"
        fi
        [ -n "$tok_str" ] && addu "${tok_str} ${net_str}"
    fi

    # Budget tracking — accumulated across billing period
    if [ -n "$period_total" ] && [ -n "$budget" ] && [ -n "$active_rate" ]; then
        budget_pct=$(echo "scale=0; $period_total * 100 / $budget" | bc 2>/dev/null)
        if [ -n "$budget_pct" ]; then
            if   [ "$budget_pct" -ge 80 ]; then bgt_color="$red"
            elif [ "$budget_pct" -ge 50 ]; then bgt_color="$yellow"
            else bgt_color="$cyan"; fi

            remaining_usd=$(echo "scale=2; $budget - $period_total" | bc 2>/dev/null)
            time_left_m=""
            if [ -n "$remaining_usd" ]; then
                cmp=$(echo "$active_rate > 0" | bc 2>/dev/null)
                [ "$cmp" = "1" ] && \
                    time_left_m=$(echo "scale=0; $remaining_usd * 60 / $active_rate" | bc 2>/dev/null)
            fi

            time_left_fmt=""
            if [ -n "$time_left_m" ] && [ "$time_left_m" -ge 0 ] 2>/dev/null; then
                tlf=$(fmt_time "$time_left_m")
                time_left_fmt=" ${dim}${tlf}${reset}"
            fi

            period_fmt=$(printf "$%.2f" "$period_total")
            addu "${bgt_color}${period_fmt}/${budget}${time_left_fmt}${reset}"
        fi
    fi
fi

printf "%b\n" "$out"

# Line 2: usage — rate limits / cost, cache, last interaction
[ -n "$usage" ] && printf "%b\n" "$usage"

# Line 3: cwd + transcript id
out2=""
if [ -n "$cwd" ]; then
    cwd_display="${cwd/#$HOME/~}"
    out2="${dim}${cwd_display}${reset}"
fi
[ -n "$transcript_file" ] && {
    [ -n "$out2" ] && out2+="${sep}"
    out2+="${dim}${transcript_file}${reset}"
}
[ -n "$wakeup_reason" ] && {
    [ -n "$out2" ] && out2+="${sep}"
    out2+="${dim}⏰ ${wakeup_reason}${reset}"
}
[ -n "$out2" ] && printf "%b\n" "$out2"

