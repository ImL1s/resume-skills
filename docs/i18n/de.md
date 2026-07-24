<!-- portable-resume-i18n: de v0.3.1 -->
# Portable Resume — deutscher Schnellstart

Portable Resume überträgt begrenzten lokalen Kontext aus Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen oder Kimi in eine **neue** Coding-Agent-Sitzung. Laufende Prozesse oder Sitzungen werden nicht wiederhergestellt. Die Reader arbeiten offline, verwenden nur die Python-Standardbibliothek, starten niemals die Quell-CLI und kennzeichnen wiederhergestellten Text als inert und nicht vertrauenswürdig.

## Installation

Erfordert Python 3.11+. Installieren Sie das veröffentlichte Paket von PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

Aus einem Checkout verwenden Sie `pipx install .`. Alle acht Ziel-host in globale Benutzerpfade installieren:

```bash
install-resume-skills quick-install all
```

Qwen nur für das aktuelle Projekt installieren:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Unterstützte Ziele sind Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code und Kimi Code CLI. Exakte Befehle für direkte Skill-, extension-, plugin- und marketplace-Installationen stehen im [Installationsleitfaden](../install-hosts.md). Prüfen Sie plugin-Inhalte und release-SHA-256 vor dem Vertrauen.

## Prüfung und Nutzung

Im Checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Aktivieren Sie `resume-<source>` mit der Syntax des Ziel-host und prüfen Sie das aktuelle repository erneut, bevor Sie den handoff ausführen.

Der [Projektstatus](../STATUS.md) trennt verifizierte Aussagen von noch nicht ausgeführten UI／release-Gates.
