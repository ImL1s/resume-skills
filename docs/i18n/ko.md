<!-- portable-resume-i18n: ko v0.3.2 -->
# Portable Resume — 한국어 빠른 시작

Portable Resume은 Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen, Kimi의 제한된 로컬 컨텍스트를 **새로운** 코딩 에이전트 세션으로 이전합니다. 실행 중인 프로세스나 세션을 복원하지 않습니다. 리더는 오프라인·Python 표준 라이브러리 전용이며 원본 CLI를 실행하지 않고, 복구된 텍스트를 비활성·신뢰할 수 없는 데이터로 표시합니다.

## 설치

Python 3.11+가 필요합니다. PyPI에서 게시된 패키지를 설치합니다:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

checkout에서는 `pipx install .`을 사용할 수 있습니다. 8개 대상 host를 사용자 전역 경로에 한 번에 설치:

```bash
install-resume-skills quick-install all
```

현재 프로젝트에 Qwen만 설치:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

대상은 Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code, Kimi Code CLI입니다. host별 직접 Skill, extension, plugin, marketplace 명령은 [설치 가이드](../install-hosts.md)를 확인하세요. plugin을 신뢰하기 전에 내용과 release SHA-256을 검증해야 합니다.

## 검증 및 사용

checkout에서 실행:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

대상 host 문법으로 `resume-<source>`를 활성화하고 handoff를 실행하기 전에 현재 repository 상태를 다시 확인하세요.

현재 로컬 host 스모크에서는 8/8 CLI 호출과 지원되는 7/7 네이티브 plugin／extension 설치가 모두 통과했습니다. 시각적 picker 상호작용과 공개 marketplace 게시는 별도의 미실행 항목입니다.

검증된 주장과 실행되지 않은 UI／release 게이트는 [프로젝트 상태](../STATUS.md)를 참조하세요.
