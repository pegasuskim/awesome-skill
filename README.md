# awesome-skill

## Skills

`skills/install.sh`가 설치하는 스킬입니다. 설치 대상은 `skills/install.json`이 정합니다. 이 파일에 없는 스킬은 Claude Code와 Codex에 모두 설치됩니다. 실험 중인 것은 `experimental/`에 있고 설치되지 않습니다.

| 스킬 | 설치 대상 | 용도 |
| --- | --- | --- |
| [handoff](skills/handoff/) | Claude Code·Codex | 지금 대화를 다른 에이전트가 이어받을 인수인계 문서로 정리 |
| [korean-technical-writing](skills/korean-technical-writing/) | Claude Code·Codex | 한국어 기술 문서의 작성·검토 기준 |
| [orch](skills/orch/) | Claude Code·Codex | Herdr pane에서 claude·codex 에이전트를 띄우고 프롬프트를 보내 최종 답만 받기 |
| [readable-artifact](skills/readable-artifact/) | Claude Code | 다른 사람이 읽을 Claude Artifact 페이지 작성 가이드 |
| [scaffold](skills/scaffold/) | Claude Code | 새 프로젝트의 아키텍처와 AI 작업 환경(CLAUDE.md·규칙·스킬·훅)을 인터뷰로 정해 `requirements.md`로 정리 |
