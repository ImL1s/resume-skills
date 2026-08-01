<!-- portable-resume-i18n: de v0.4.0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — deutscher Schnellstart

**Aktuelle veröffentlichte Version:** [`0.4.0`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.0)

Portable Resume überträgt begrenzten lokalen Kontext aus Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen oder Kimi in eine **neue** Coding-Agent-Sitzung. Laufende Prozesse oder Sitzungen werden nicht wiederhergestellt. Die Reader arbeiten offline, verwenden nur die Python-Standardbibliothek, starten niemals die Quell-CLI und kennzeichnen wiederhergestellten Text als inert und nicht vertrauenswürdig.

## Installation

Erfordert Python 3.11+. Installieren Sie das veröffentlichte Paket von PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

<!-- portable-resume-current-registry:begin -->
Aus einem Checkout von aktuellem `main` verwenden Sie `pipx install .`. Alle 18 Ziel-host in globale Benutzerpfade installieren:

```bash
install-resume-skills quick-install all
```

Qwen nur für das aktuelle Projekt installieren:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Auf `main` aktivierte Ziele sind Antigravity / agy, Claude Code, Cline, Codex CLI / IDE, Crush, Cursor Agent, Gemini CLI, GitHub Copilot CLI, goose, Grok Build, Hermes Agent, Kilo CLI, Kimi Code CLI, OpenClaw, OpenCode, OpenHands, Pi agent und Qwen Code.
<!-- portable-resume-current-registry:end -->

Veröffentlichtes `0.4.0` umfasst neun Ziele inklusive Pi (Dateisystem; native UI not-run). Exakte Befehle für direkte Skill-, extension-, plugin- und marketplace-Installationen stehen im [Installationsleitfaden](../install-hosts.md). Prüfen Sie plugin-Inhalte und release-SHA-256 vor dem Vertrauen.

## Öffentlicher Marketplace

Der öffentliche
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
bietet native Installation für sechs kompatible Hosts:

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

Der Leitfaden enthält die verifizierten Wege für Cursor, Qwen, Grok und Kimi sowie direkte Alternativen für Antigravity und OpenCode.

## Prüfung und Nutzung

Im Checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Aktivieren Sie `resume-<source>` mit der Syntax des Ziel-host und prüfen Sie das aktuelle repository erneut, bevor Sie den handoff ausführen.

Der Host-Smoke-Test bestand 8/8 CLI-Aufrufe und 7/7 exakte lokale native Paketinstallationen. Die Installation aus dem öffentlichen Marketplace bestand auf 6/6 kompatiblen Hosts; auch die Marketplace-Picker von Cursor und Kimi bestanden. Andere visuelle Skill-Picker und kuratierte Herstellerverzeichnisse werden nicht als abgeschlossen beansprucht.

Diese Ergebnisse auf Host-Ebene stammen aus der v0.3.2-Evidenz. Die Host-für-Host-Neuinstallation und Picker-Abläufe für v0.4.0 bleiben **not-run**.
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.3.4-host-reinstall-not-run -->

Der [Projektstatus](../STATUS.md) trennt verifizierte Aussagen von noch nicht ausgeführten UI／release-Gates.
