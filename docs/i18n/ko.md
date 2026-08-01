<!-- portable-resume-i18n: ko v0.4.0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — 한국어 빠른 시작

**현재 공개 릴리스:** [`0.4.0`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.0)

Portable Resume은 Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi의 제한된 로컬 컨텍스트를 **새로운** 코딩 에이전트 세션으로 이전합니다. 실행 중인 프로세스나 세션을 복원하지 않습니다. 리더는 오프라인·Python 표준 라이브러리 전용이며 원본 CLI를 실행하지 않고, 복구된 텍스트를 비활성·신뢰할 수 없는 데이터로 표시합니다.

## 설치

Python 3.11+가 필요합니다. PyPI에서 게시된 패키지를 설치합니다:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

<!-- portable-resume-current-registry:begin -->
현재 `main` checkout에서는 `pipx install .`을 사용할 수 있습니다. 18개 대상 host를 사용자 전역 경로에 한 번에 설치:

```bash
install-resume-skills quick-install all
```

현재 프로젝트에 Qwen만 설치:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

`main`에서 활성화된 대상은 Antigravity / agy, Claude Code, Cline, Codex CLI / IDE, Crush, Cursor Agent, Gemini CLI, GitHub Copilot CLI, goose, Grok Build, Hermes Agent, Kilo CLI, Kimi Code CLI, OpenClaw, OpenCode, OpenHands, Pi agent, 그리고 Qwen Code입니다.
<!-- portable-resume-current-registry:end -->

게시된 `0.4.0`은 Pi(파일시스템 설치)를 포함한 9개 대상입니다(네이티브 UI는 not-run). host별 직접 Skill, extension, plugin, marketplace 명령은 [설치 가이드](../install-hosts.md)를 확인하세요. plugin을 신뢰하기 전에 내용과 release SHA-256을 검증해야 합니다.

## 공개 marketplace

공개
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)는
호환되는 6개 host에 네이티브 설치 경로를 제공합니다:

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

검증된 Cursor, Qwen, Grok, Kimi 경로와 Antigravity／OpenCode 직접 설치 대안은 설치 가이드에 있습니다.

## 검증 및 사용

checkout에서 실행:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

대상 host 문법으로 `resume-<source>`를 활성화하고 handoff를 실행하기 전에 현재 repository 상태를 다시 확인하세요.

현재 host 스모크는 8/8 CLI 호출과 정확한 로컬 네이티브 패키지 7/7 설치를 통과했습니다. 공개 marketplace 설치는 호환되는 6/6 host에서 통과했고 Cursor와 Kimi marketplace picker도 통과했습니다. 다른 시각적 Skill picker와 공급업체 선정 디렉터리는 완료로 주장하지 않습니다.

이 host 수준 결과는 v0.3.2 시점의 증거입니다. v0.4.0의 host별 재설치 및 picker 흐름은 아직 **not-run**입니다.
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.3.4-host-reinstall-not-run -->

검증된 주장과 실행되지 않은 UI／release 게이트는 [프로젝트 상태](../STATUS.md)를 참조하세요.
