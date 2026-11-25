#!/bin/bash
# herdr: 현재 pane 닫기
#   유휴          -> 조용히 즉시 닫음 (화면 변화 없음)
#   실행 중       -> 토스트 표시. 5초 안에 다시 누르면 닫음.
#
# herdr 0.8.2 에는 pane 닫기 확인 기능이 없어 커스텀 명령으로 구현.
# popup 대신 type="shell" 을 쓰는 이유: popup 은 명령 실행 전에 먼저 열려서
# 유휴 pane 에서도 창이 깜빡임. shell 은 UI 가 없어 깜빡임이 없다.
# 위치:   ~/.config/herdr/herdr-close-pane.sh
# 바인딩: config.toml [[keys.command]] key="prefix+alt+x"
#         kitty 가 cmd+w 를 combine 으로 prefix+alt+x 로 중계.

set -u
HERDR="${HERDR_BIN_PATH:-herdr}"
WINDOW=1   # 재입력 대기 시간(초)

pane_id="${HERDR_PANE_ID:-}"
[ -z "$pane_id" ] && pane_id=$("$HERDR" pane list 2>/dev/null \
  | jq -r '.result.panes[]? | select(.focused == true) | .pane_id' | head -1)
[ -z "$pane_id" ] && pane_id=$("$HERDR" pane current 2>/dev/null \
  | jq -r '.result.pane.pane_id // empty')

if [ -z "$pane_id" ]; then
  "$HERDR" notification show "pane 닫기 실패" --body "pane 을 특정하지 못했습니다" 2>/dev/null
  exit 1
fi

info=$("$HERDR" pane process-info --pane "$pane_id" 2>/dev/null)
shell_pid=$(printf '%s' "$info" | jq -r '.result.process_info.shell_pid // empty')
fg_pgid=$(printf '%s' "$info" | jq -r '.result.process_info.foreground_process_group_id // empty')

# 셸이 곧 포그라운드 프로세스 그룹이면 유휴. (유휴 pane 도 목록에 zsh 자신이 들어옴)
if [ -n "$shell_pid" ] && [ "$fg_pgid" = "$shell_pid" ]; then
  "$HERDR" pane close "$pane_id" >/dev/null 2>&1
  exit 0
fi

state="${TMPDIR:-/tmp}/herdr-close-pane-${pane_id//:/_}"
now=$(date +%s)

# 2회차 입력인가?
if [ -f "$state" ]; then
  prev=$(cat "$state" 2>/dev/null || echo 0)
  if [ $(( now - prev )) -le "$WINDOW" ]; then
    rm -f "$state"
    "$HERDR" pane close "$pane_id" >/dev/null 2>&1
    exit 0
  fi
fi

# 1회차 -> 대기 상태 기록 후 토스트
printf '%s' "$now" > "$state"

running=$(printf '%s' "$info" | jq -r --arg sp "$shell_pid" '
  .result.process_info.foreground_processes[]?
  | select((.pid|tostring) != $sp)
  | (.argv0 // .name) | split("/") | last' 2>/dev/null | paste -sd ", " -)
[ -z "$running" ] && running="알 수 없는 프로세스"

"$HERDR" notification show "pane 닫기" \
  --body "${running} 실행 중 — ${WINDOW}초 안에 cmd+w 를 다시 누르면 닫습니다" \
  --sound none 2>/dev/null
