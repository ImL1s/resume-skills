<!-- portable-resume-i18n: ru v0.3.2 -->
# Portable Resume — краткое руководство на русском

**Текущий опубликованный выпуск:** [`0.3.2`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2)

Portable Resume переносит ограниченный локальный контекст из Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen или Kimi в **новую** сессию программного агента. Это не восстановление работающего процесса или сессии. Читатели работают без сети, используют только стандартную библиотеку Python, никогда не запускают исходный CLI и помечают восстановленный текст как инертный и недоверенный.

## Установка

Требуется Python 3.11+. Установите опубликованный пакет из PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

Из checkout используйте `pipx install .`. Установка всех восьми целевых host в пользовательские каталоги:

```bash
install-resume-skills quick-install all
```

Установка Qwen только для текущего проекта:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Поддерживаются Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code и Kimi Code CLI. Точные команды для Skill, extension, plugin и marketplace приведены в [руководстве по установке](../install-hosts.md). Перед доверием к plugin проверьте его содержимое и SHA-256 release.

## Проверка и использование

В checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Активируйте `resume-<source>` по правилам целевого host и заново проверьте текущий repository перед выполнением handoff.

Локальная проверка host успешно выполнила 8/8 вызовов CLI; точные пакеты `0.3.2` прошли 7/7 установок поддерживаемых нативных plugin／extension. Взаимодействие с визуальным picker и публикация в открытых marketplace остаются отдельными невыполненными проверками.

[Статус проекта](../STATUS.md) отделяет подтверждённые результаты от ещё не запущенных UI／release-проверок.
