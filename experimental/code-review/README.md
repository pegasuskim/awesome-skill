# 로컬 Codex 코드 리뷰

여러 Git 저장소에 설치 파일을 넣지 않고, 저장소 경로와 기준 브랜치를 받아
변경의 엣지케이스를 조사하는 CLI입니다. Python 표준 라이브러리와 설치된
Codex CLI를 사용합니다. 그래프 인덱스를 만드는 도구는 아닙니다.

실제 버그 탐지율과 지적의 정확도를 개선하는 데 필요한 후보별 검증 기록,
코드 근거, 실행 증거와 사람의 판정을 남깁니다. Greptile과 동등한 품질은
아직 검증하지 않았습니다.

추가 작업은 [TODO.md](TODO.md)에 정리합니다.

## 병렬 실행 (0.3.0)

기본 실행 방식은 `parallel`입니다. 기존 명령을 그대로 사용하면 최대 4개 작업을
동시에 실행하며 모델·추론 수준·Fast 설정은 변경하지 않습니다.

```bash
python3 /path/to/code-review/review.py review \
  --repo /path/to/project --base origin/main \
  --model gpt-6.1-sol --reasoning max --depth deep --run-tests \
  --workers 4 --output-dir "$HOME/.cache/code-review/runs"
```

디렉터리와 상대 import를 참고해 변경 경로를 그룹에 빠짐없이 배정합니다.
각 탐색은 그룹 밖의 호출자·계약도 조사할 수 있고, 여러 그룹이거나 `deep`이면
전체 변경의 상호작용을 조사하는 작업도 병행합니다. 인덱스는 **문자열 기반 상대
import 힌트이며 AST·완전한 호출 그래프가 아닙니다.** 별칭·동적 호출·소비자는
추가 탐색 대상입니다. 공통 원문 발췌는 120줄까지이며 전체 코드의 대체물이 아닙니다.

각 탐색의 최종 JSON을 검증하면 다른 탐색의 종료를 기다리지 않고 후보를 검증합니다.
기본은 작업당 후보 1개이며 `--verify-batch-size 2`처럼 늘릴 수 있습니다.
검증 중 새로 발견한 후보도 등록·검증합니다. `--max-followup-rounds`(기본 2)
초과 후보는 미확인으로 남깁니다. 마지막 정리 작업은 전체 변경의 요약·점수를
평가하고 확인된 후보의 동일 원인·동일 발생 조건에 한해 중복을 병합합니다.
미확인 후보를 확인으로 승격하거나 높은 우선순위를 낮은 우선순위로 숨기지 않습니다.

탐색 checkout은 읽기 전용으로 공유합니다. 환경 준비·회귀 검사와 재현 검증은
별도 `validation-checkout/`에서 실행합니다. 준비·회귀 검사가 끝난 뒤 쓰기 검증은
한 번에 하나만 실행하고 작업별 재현 경로를 사용합니다. 준비 실패 시 원래 checkout에서
정적으로 검증합니다. 기존 소스 변경을 검사하고 지적의 코드 근거는 고정된 입력 트리를
참조해야 합니다. 실패 작업·미검토 범위는 최종 한계에 남깁니다.

### 환경 준비와 회귀 검사

`--run-tests`만으로 설치·회귀 명령을 추측하지 않습니다. 명시한 명령만 실행하며
모델에는 반복 설치·다운로드를 금지합니다. 준비와 회귀 검사는 탐색과 병행하고
**후보가 없어도** 실행합니다. 명령·테스트 경로는 저장소에 맞춰 변경하세요.

```bash
python3 /path/to/code-review/review.py review \
  --repo /path/to/project --base origin/main --depth deep \
  --model gpt-6.1-sol --reasoning max --run-tests --workers 4 \
  --setup-command 'pnpm install --offline --frozen-lockfile' \
  --test-command 'pnpm exec vitest run test/unit/scripts' \
  --setup-timeout 180 --test-timeout 300
```

offline 설치는 기존 pnpm 캐시를 사용하며 부족하면 실패합니다. 캐시를 자동
다운로드하거나 원본의 `node_modules`를 복사하지 않습니다. 준비 실패 후 회귀 검사는
생략합니다. 회귀 명령 하나가 실패해도 나머지 회귀 명령은 실행합니다. 실패·시간 초과와
전체 로그를 보관하며 환경/테스트 실패 자체를 제품 버그로 확정하지 않습니다.
소스를 변경한 환경은 검증에 사용하지 않습니다.

명령 옵션은 반복 가능합니다. argv로 실행하므로 셸 변수·파이프·`&&`는 자동 해석하지
않습니다. 셸이 필요하면 명시적으로 `sh -lc '...'`를 지정하세요. 작업 디렉터리는 검증
checkout이며, 지정 명령은 로컬 프로세스로 실행하고 Codex 샌드박스 명령이 아닙니다.

반복 사용 시 [설정 예제](examples/checks.pnpm.json)를 복사·수정한 뒤
`--checks-config /path/to/checks.json`을 지정하세요. `setup`·`tests`는 argv 배열의 목록,
`groups`는 그룹 이름과 상대 경로 glob 목록입니다. 미배정 변경도 자동 그룹에 포함하고
중복 배정은 오류입니다. config 명령 뒤에 CLI 명령을 추가하므로 중복 지정하지 마세요.
사용자가 직접 지정한 파일만 읽으며 저장소 설정을 자동 실행하지 않습니다.

### 결과와 비교

- `report.md`: 최종 지적·요약·준비/회귀 검사 상태.
- `performance.json`: 전체 시간, 단계·명령별 시간, Codex가 보고한 토큰 사용량.
- `work-plan.json`, `context-pack.json`: 변경 배정과 공통 문맥·참조 힌트.
- `checks.json`, `setup-*.log`, `tests-*.log`: 설정된 검사 결과와 전체 출력.
- `discover-*.json`, `crosscut.json`, `verify-*.json`, `reconcile.json`: 작업별 원본 결과.
- `candidates.json`, `verdicts.json`, `candidate-links.json`: 후보·판정·동일 후속 가설 연결.

`--timeout`은 Codex 작업 각각의 제한이며 전체 리뷰 제한이 아닙니다. `--workers`에는
환경 준비도 포함합니다. `--dry-run`은 모델·설치·테스트 없이 계획과 프롬프트를 저장합니다.
이전 방식과 비교하려면 같은 SHA·모델·추론 수준에서 `--execution serial`로 실행하세요.
serial은 새 설치·회귀 명령·그룹 설정을 지원하지 않습니다.

속도·품질 효과는 아직 측정하지 않았습니다. 병렬 작업은 전체 모델 사용량을 늘릴 수
있으며 쓰기 검증·전체 상호작용 조사·최종 정리는 순차 의존성이 있습니다. 10배 단축이나
동등한 탐지율을 보장하지 않습니다. 실제 버그·오탐과 실행 시간을 함께 비교하세요.

## 바로 사용하기

필요한 환경은 Python 3.10 이상, Git, `codex exec`의 `--output-schema`,
`--json`, `--ephemeral`을 지원하는 Codex CLI입니다. 개발 시 확인한 CLI는
`0.160.0`입니다. 기존 Codex 로그인과 모델 설정을 그대로 사용합니다.

```bash
codex login

python3 /path/to/awesome-config/experimental/code-review/review.py review \
  --repo /path/to/company-repo \
  --base origin/main
```

어느 디렉터리에서 실행해도 됩니다. `--repo`는 리뷰할 Git 저장소의 **루트**여야
합니다. PR을 생성하지 않아도 로컬 브랜치·커밋의 차이를 리뷰할 수 있습니다.
브랜치는 미리 checkout하거나 `--head`로 지정하세요. 기준은 병합할 대상
브랜치에 맞춥니다. `--base`를 생략하면 `origin/HEAD`, `origin/main`,
`origin/master`, `main`, `master` 순서로 로컬에 있는 ref를 찾습니다.
원격 ref를 자동 fetch하지 않으므로 최신 기준이 필요하면 직접 갱신하세요.

`Needed a single revision` 또는 ref 해석 오류가 나면 `--base`/`--head`로 지정한
브랜치나 커밋을 대상 저장소에서 찾을 수 있는지 확인하세요. `--repo .`는 명령을
실행한 디렉터리를 가리킵니다. 그 디렉터리에서 `git rev-parse --show-toplevel`과
`git branch -a`로 저장소 루트와 로컬에 존재하는 ref를 확인할 수 있습니다.
원격에 `develop`이 실제로 있고 로컬 ref만 없다면
`git fetch origin refs/heads/develop:refs/remotes/origin/develop`으로 가져온 뒤
`--base origin/develop`을 사용하세요. PR 대상이 `main`이라면 `--base origin/main`을
사용합니다. 자동으로 다른 기준 브랜치로 대체하지는 않습니다.

```bash
# 현재 HEAD에 staged/unstaged/untracked 변경까지 포함
python3 /path/to/awesome-config/experimental/code-review/review.py review \
  --repo /path/to/company-repo --base origin/main --uncommitted

# 별도 브랜치나 커밋을 리뷰 (원본의 현재 브랜치를 바꾸지 않음)
python3 /path/to/awesome-config/experimental/code-review/review.py review \
  --repo /path/to/company-repo --base origin/main --head feature/payment

# 추가 탐색과 로컬 재현 테스트 허용
python3 /path/to/awesome-config/experimental/code-review/review.py review \
  --repo /path/to/company-repo --base origin/main --depth deep --run-tests

# 같은 도구로 다른 저장소 리뷰
python3 /path/to/awesome-config/experimental/code-review/review.py review \
  --repo /path/to/another-repo --base develop
```

기본 설정은 커밋된 변경만 리뷰하고, 원본의 미커밋 변경은 제외했다고 기록합니다.
`--uncommitted`는 현재 HEAD에만 사용할 수 있으며 Git에서 무시한 파일은
포함하지 않습니다. 변경 중인 파일의 복사 일관성이 깨지면 실행을 중단합니다.

PR 설명, 의도한 동작, 팀의 중요한 계약을 파일로 전달하면 오탐 판별에 도움이
됩니다. 파일을 여러 번 지정할 수 있습니다. 적용 범위와 허용되는 예외도 적으세요.

```bash
python3 /path/to/awesome-config/experimental/code-review/review.py review \
  --repo /path/to/company-repo --base origin/main \
  --context /path/to/pr-description.md \
  --context /path/to/payment-contracts.md
```

모델과 추론 수준은 기본적으로 기존 Codex 설정을 따릅니다. 필요하면
`--model <사용 가능한 모델>`과 `--reasoning xhigh`로 지정할 수 있습니다.
지원하지 않는 모델/추론 수준은 Codex가 오류로 반환합니다.

`--reasoning`의 명시 옵션은 `minimal`, `low`, `medium`, `high`, `xhigh`,
`max`입니다. 모델과 클라이언트가 지원하면 `--reasoning max`를 사용할 수
있습니다. Codex 대화형 CLI의 `/model`에서 모델을 선택한 뒤
`More reasoning…`으로 지원 수준을 확인하세요.
[OpenAI 공식 모델 문서](https://learn.chatgpt.com/docs/models)에 따르면 Max는
한 작업에 더 많은 추론을 사용하고, Ultra는 하위 에이전트로 작업을 병렬 처리합니다.
현재 도구의 병렬 작업은 별도 Codex 프로세스이며, 각 세션에는 하위 에이전트를
실행하지 않도록 지시합니다. Ultra의 하위 에이전트 결과·실행 증거를 합치는 방식은
아직 구현하지 않았으므로 명시 옵션으로 제공하지 않습니다.

## 다른 개발자가 로컬에서 실행하기

현재는 Python 패키지 설치 없이 `code-review/` 폴더를 받아 실행할 수 있습니다.
`review.py`, `pipeline.py`와 `prompts/`를 함께 전달하세요. `runs/`는 공유할 실행 파일이 아니며,
대상 저장소의 코드와 로그가 들어 있는 개인별 리뷰 이력입니다. 다른 저장소에
도구를 복사할 필요 없이 `--repo`만 바꾸면 됩니다.

각 개발자는 Python 3.10 이상, Git과 Codex CLI를 설치하고 자기 계정으로
로그인합니다. 설치 방법은 [OpenAI 공식 Codex CLI 문서](https://learn.chatgpt.com/docs/codex/cli),
인증 방법은 [OpenAI 공식 인증 문서](https://learn.chatgpt.com/docs/auth)를 참고하세요.
`codex exec`는 저장된 CLI 인증을 재사용하므로 로컬 사용에 별도 API 키를
필수로 요구하지 않습니다.

```bash
python3 --version
git --version
codex --version
codex login
codex login status

# 리뷰할 브랜치를 checkout한 상태에서 실행. origin/main은 PR 대상에 맞게 변경.
# 필요한 원격 ref는 이 명령을 실행하기 전에 직접 fetch.
python3 /path/to/code-review/review.py review \
  --repo /path/to/project \
  --base origin/main \
  --head HEAD \
  --depth deep \
  --reasoning xhigh \
  --run-tests \
  --output-dir "$HOME/.cache/code-review/runs"
```

터미널에 출력된 경로의 `report.md` 상단에서 Confidence Score와 Summary를
읽고, 아래의 확인된 지적, 미확인 후보와 한계를 확인하세요. 종료 코드 3은
보고서가 생성된 미완료 리뷰입니다. 버그가 없다는 의미로 처리하지 마세요.
`--dry-run`을 추가하면 모델 호출 없이 입력 준비를 확인할 수 있습니다.

팀에서 같은 실행 조건을 사용하려면 도구 버전, Codex CLI 버전, 모델,
`xhigh`, 기준/head SHA, 추가 문맥을 맞추세요. `--model`을 생략하면 개인의
설정을 따르므로 모델도 같다고 보장하지 않습니다. 같은 조건에서도 모델의
결과가 매번 같거나 모든 버그를 발견한다고 보장하지는 않습니다.

과거 PR 실험에서는 설치·회귀 테스트를 별도로 실행했습니다. 이제 병렬 모드의
`--setup-command`·`--test-command` 또는 `--checks-config`로 재현할 수 있습니다.
새 checkout에는 원본의 `node_modules`나 `.venv`가 없으므로 준비 명령을 지정하세요.

팀용으로 설치 후 한 명령에 전체 과정을 실행하려면 다음 기능을 추가해야 합니다.
아래 명령과 설정은 구현 방향이며 현재 CLI가 제공하는 기능은 아닙니다.

| 추가 기능 | 담당할 작업 |
| --- | --- |
| 설치 가능한 CLI 패키지 | `review.py`, `pipeline.py`와 프롬프트를 함께 버전 관리하고 `code-review` 명령 제공. 기본 출력은 설치 폴더 밖의 사용자별 경로에 저장. |
| 실행 환경 검사 (`doctor`) | Python/Git/Codex 버전, 로그인 상태, 필수 CLI 옵션, 저장소별 런타임·패키지 매니저 확인. |
| 저장소별 실행 설정 확대 | 구현된 설치·회귀·그룹 설정에 팀 모델·추론 수준·문맥 기본값 관리 추가. |
| 환경 준비 확대 | 현재 명시 명령 실행에 런타임별 환경 검사와 캐시 호환성 관리 추가. |
| PR 입력 지원 | PR URL에서 대상/head SHA와 설명을 읽고 SHA를 고정. 이후 원본 브랜치가 바뀌어도 고정된 변경을 리뷰. GitHub 기능을 사용할 때만 별도 GitHub 인증 필요. |

다음 우선순위는 **품질·속도 평가 → 패키지 설치와 환경 검사 → PR URL 지원**입니다.
현재 리뷰의 탐색·반박·근거 검사를 유지하면서, 사람이
수동으로 준비했던 실행 환경을 재현 가능하게 만드는 것이 목적입니다. 로컬
서버나 외부 서비스가 필요한 테스트도 설정에 명시하고, 사용할 수 없으면 그
검증은 미확인으로 남깁니다.

## 실행 과정

1. 기준과 head를 커밋 SHA로 고정하고 merge-base를 계산합니다.
2. 실행 폴더에 독립된 Git checkout을 만듭니다. 원본의 checkout, index,
   커밋은 수정하지 않습니다. `--uncommitted`일 때 변경을 이 복사본에 적용합니다.
3. 공통 문맥과 변경 배정을 준비하고 탐색 작업을 병렬 실행합니다.
   관련 호출자·하위 호출·스키마·테스트·설정은 그룹 밖에서도 조사합니다.
4. 여러 그룹이거나 `deep`이면 전체 변경의 상호작용 조사도 병렬 실행합니다.
   `--run-tests`일 때 명시한 설치·회귀 명령도 별도 checkout에서 병행합니다.
5. 탐색 결과가 반환되면 **검증:** 각 후보를 반박할 기존 검증·잠금·트랜잭션·예외를
   찾습니다. 판정을 `confirmed`, `refuted`, `unresolved`, `duplicate`로 남깁니다.
6. 실행기가 모든 후보의 판정 누락·중복, 실제 파일/줄 참조, 필수 근거를
   검사합니다. 근거가 부족한 확인 판정은 미확인으로 바꿉니다.
7. 필요한 최종 정리 후 Confidence Score, 변경·검토 요약, 확인된 문제,
   모든 후보의 판정, 검토 범위·한계와 시간을 저장합니다.

`--execution serial`은 기존 탐색→deep 추가 탐색→후보 검증을 유지합니다.

탐색은 읽기 전용 정적 조사입니다. `--run-tests`는 검증 복사본에서 쓰기를
허용하고, 병렬 모드의 재현 파일은 `.review-repros/verify-작업번호/`에 만들도록 지시합니다. 기존 파일이
바뀌면 결과를 확정하지 않습니다. 원본의 `node_modules`, `.venv`, 빌드 결과
등 Git에서 무시한 파일은 복사하지 않습니다. 필요한 의존성이나 서비스가 없어
재현하지 못하면 미확인/한계로 기록합니다. 서브모듈도 자동 다운로드하지 않습니다.

`--run-tests`만으로 회귀 명령을 선택하지 않습니다. 병렬 모드에서는 명시한 준비·
회귀 명령을 후보 유무와 관계없이 실행합니다. serial에서는 후보 검증 중 실행 허용만
하며 회귀 검사는 별도로 실행해야 합니다. 설정된 검사와 모델 재현은 구분해 기록합니다.

정적 근거로 확인된 버그도 보고할 수 있습니다. 실행 검증을 주장하려면
`codex --json`의 완료된 명령 실행 이벤트에 해당 명령이 있어야 합니다.
로그가 있어도 예상 동작이나 테스트 자체가 잘못됐을 수 있으므로, 이 검사는
버그의 의미를 기계적으로 증명하지는 않습니다.

완료는 모든 버그를 발견했다는 뜻이 아닙니다. 일부 경로가 미검토이거나 후보가
미확인이거나 모델이 조사 한계를 보고하면 상태는 `incomplete`입니다. 실행 실패와 미완료 결과는 깨끗한 리뷰로
표시하지 않습니다.

| 종료 코드 | 의미 |
| --- | --- |
| 0 | 완료 또는 dry-run 준비 완료; 버그 개수와 무관 |
| 2 | 입력/Git/Codex/검증 오류 |
| 3 | 리뷰는 생성했지만 미검토 파일 또는 미확인 후보가 있음 |
| 130 | 사용자가 중단함 |

## Summary와 Confidence Score

`report.md` 상단에는 변경의 목적과 내용, 최종 검토 결과, 판정별 개수,
파일 검토 범위와 실행 기록으로 확인한 재현 개수가 표시됩니다.
`summary.json`에는 같은 요약과 점수, 단계별 모델 평가와 실행기 보정 근거를
구조화해서 저장합니다. 병렬 모드의 최종 정리는 전체 변경 요약·평가와 의미적 중복을
판단하며, 단일 탐색·검증만 있으면 별도 정리 호출을 생략합니다. serial의 변경 요약은
마지막 탐색 결과를 사용하며 후보가 있으면 검증 평가를 반영하고, 후보 없는 deep
리뷰는 두 탐색 평가 중 낮은 점수를 사용합니다.

[Greptile의 Confidence Score](https://www.greptile.com/content-library/how-to-evaluate-code-review-tools)는
PR의 머지 준비 상태를 5점으로 평가합니다. 여기서도 같은 의미의 **1–5점 평가**를
제공하지만, 아래 기준은 이 도구의 자체 기준입니다. Greptile의 내부 계산을
재현하거나 버그 확률·리뷰 정확도를 측정한 점수는 아닙니다.

| 점수 | 평가 기준 |
| --- | --- |
| 1/5 | 치명적인 문제 또는 안전하게 평가하기에 근거가 매우 부족함 |
| 2/5 | 머지 전에 고쳐야 할 심각한 문제 |
| 3/5 | 의미 있는 수정 또는 중요한 미확인 사항이 남음 |
| 4/5 | 높은 확신이 있지만 작은 수정이나 제한된 검증이 남음 |
| 5/5 | 확인된 문제·미확인 사항·검토 한계가 없고, 전체 변경을 검토했으며 필요한 검증이 충분하다고 판단 |

모델은 점수와 구체적인 이유를 함께 반환합니다. 실행기는 **정규화된 최종
판정**을 기준으로 확인된 P0/P1/P2/P3 문제가 있으면 각각 최대 1/2/3/4점,
미확인 후보·미검토 파일·미완료 상태가 있으면 최대 3점으로 제한합니다.
그 외 기록된 한계가 있어도 최대 4점입니다. 여러 제한 중 가장 낮은 상한을
적용하며, 모델이 낮게 평가한 점수를 올리지는 않습니다. 모델의 5점 평가가
참조 오류 등으로 보정되면 보고서 요약에도 최종 미확인 판정을 반영합니다.

5/5는 모델의 검토 범위에서 나온 판단이며, 자동 머지 승인이나 무결점 보장이
아닙니다. 문서 변경처럼 정적 검증으로 충분한 경우에도 나올 수 있습니다.
`--run-tests`만으로 테스트가 실행됐다고 간주하지 않습니다. 재현 개수는
실행 로그가 확인된 `runtime` 지적의 개수이며 전체 회귀 테스트 통과 여부가
아닙니다. 변경이 없으면 **미산정**, 실패·중단·dry-run이면 점수를 게시하지
않습니다. 기존 실행 이력에는 점수를 소급해서 채우지 않습니다.

## `runs/`와 피드백

기본 출력은 도구 옆의 `runs/<시각>-<ID>/`입니다. 저장 위치는
`--output-dir /path/to/review-history`로 바꿀 수 있습니다.

```text
runs/<review-id>/
├── manifest.json             # 입력 커밋, 실행 설정, 상태, 한계
├── checkout/                 # 리뷰에 사용한 독립 Git checkout
├── change.diff               # 커밋·추적 파일 diff; untracked는 inventory로 제공
├── context.json              # 제공한 PR 설명과 계약
├── discover.*                # 프롬프트, 스키마, 응답, 이벤트, 명령 로그
├── challenge.*               # deep 모드의 추가 탐색
├── verify.*                  # 후보별 검증과 실행 기록
├── candidates.json
├── verdicts.json
├── findings.json              # confirmed 판정만 포함
├── summary.json               # 요약, 최종 점수, 단계별 평가·보정 근거
├── report.md                  # Confidence Score + Summary + 상세 지적
└── feedback.jsonl            # 사람이 판정한 결과
```

`runs/`는 생성 결과라 Git에서 제외합니다. 코드, 프롬프트와 문서는 커밋합니다.
평가 사례로 보관할 결과는 필요한 내용만 별도 관리하세요. 실행 결과에는 대상
저장소의 복사본과 코드·로그가 포함됩니다.

`experiments/`는 실제 PR 리뷰 실험의 요약을 Git에 남기는 폴더입니다.
리뷰한 커밋·설정, Greptile 지적과의 비교, 재현 결과와 한계를 기록해 이후
품질 개선의 근거로 사용합니다. 현재 PR 308·313 비교와 PR 319 및 의도적으로
버그를 넣은 별도 복사본의 탐지 실험을 보관합니다. CLI는 이 폴더를 읽지 않으며,
리뷰 실행이나 자동 학습에 사용하지 않습니다. `runs/`는 원본 실행 기록,
`experiments/`는 사람이 정리해 커밋한 평가 요약입니다.

```bash
python3 /path/to/awesome-config/experimental/code-review/review.py feedback \
  --run /path/to/review-history/<review-id> \
  --candidate C0001 --label true_positive \
  --note '동일 이벤트 재전송으로 중복 저장을 재현함'

python3 /path/to/awesome-config/experimental/code-review/review.py feedback \
  --run /path/to/review-history/<review-id> \
  --candidate C0002 --label false_positive \
  --note '이 경로에도 DB 고유 제약과 충돌 처리가 적용됨'

python3 /path/to/awesome-config/experimental/code-review/review.py feedback \
  --run /path/to/review-history/<review-id> \
  --candidate M0001 --label missed \
  --note 'handler.ts:42에서 빈 배열 입력으로 실패; 사람이 발견함'

python3 /path/to/awesome-config/experimental/code-review/review.py stats \
  --runs /path/to/review-history
```

`uncertain`도 사용할 수 있습니다. 같은 후보를 다시 판정하면 최신 라벨을
집계하고, 기존 이력은 보존합니다. 유효 지적 비율과 오탐 비중은 사람이 판정한
확인 지적만 집계합니다. 탐지율은 기록한 실제 버그와 missed 사이의 비율이라
전체 버그 탐지율을 보장하지 않습니다. 일부 PR로 규칙을 개선하고, 별도로
남겨 둔 PR로 평가하세요. 피드백을 자동으로 광범위한 억제 규칙으로 바꾸지는 않습니다.

## 호출 없이 준비하기와 테스트

```bash
python3 /path/to/awesome-config/experimental/code-review/review.py review \
  --repo /path/to/company-repo --base origin/main --dry-run

python3 -m unittest discover -s /path/to/awesome-config/experimental/code-review/tests -v
```

`--dry-run`은 커밋·변경 목록·checkout·탐색 입력을 준비하며 Codex를 호출하지
않습니다. 테스트는 임시 Git 저장소와 가짜 Codex 프로세스로 원본 보존,
커밋 범위, 미커밋 변경, 판정 누락, 참조 오류, 실행 증거, 실패·시간 초과와
피드백 집계를 확인합니다. 실제 모델의 탐지 품질 평가와는 별개입니다.

로컬은 코드 탐색과 테스트가 로컬 checkout에서 실행된다는 뜻입니다.
기본 Codex 모델 추론과 인증에는 기존 Codex 서비스 연결을 사용합니다.

## 참고

- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode):
  `exec`, JSON 이벤트, 출력 스키마와 기존 CLI 인증 사용
- [Codex 리뷰 규칙](https://developers.openai.com/blog/custom-code-review-rules-for-codex):
  중요한 계약, 적용 범위와 허용되는 예외를 짧은 규칙으로 제공
- [Greptile v3](https://www.greptile.com/blog/greptile-v3-agentic-code-review):
  관련 코드 반복 탐색과 가설 검증
- [Greptile TREX](https://www.greptile.com/blog/trex): 실행 결과와 증거를 리뷰에 포함
