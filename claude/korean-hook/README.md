# korean-hook

도구 호출 사이의 진행 메시지까지 한국어로 나오게 하는 임시 hook입니다.

## 왜 만들었나

- Claude Code CLI 2.1.301부터 진행 메시지가 한국어로 나오지 않는 이슈가 생겼습니다.
- 이슈가 개선되면 이 hook은 삭제할 예정입니다.

## 동작

- `PreToolUse`, `PostToolUse` 때마다 "한국어로 작성하라"는 문장을 Claude의 컨텍스트에 넣습니다.
- 이 문장은 턴을 시작할 때 한 번만 들어가지 않고, 도구 결과마다 바로 옆에 붙습니다.

## 켜고 끄기

실험용이라 기본으로는 꺼져 있습니다. Claude Code를 실행하는 셸에서 아래 변수를 export하면 켜집니다.

```bash
export HONG_CLAUDE_EXPERIMENT='{"korean-context":true}'
```

- `korean-context` 값이 `true`가 아니거나 변수가 없으면 꺼집니다.
- 변수는 세션이 시작될 때 읽힙니다. 값을 바꾸면 그 뒤에 새로 띄운 세션부터 적용됩니다.
