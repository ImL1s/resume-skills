<!-- portable-resume-i18n: fr v0.3.3 -->
# Portable Resume — démarrage rapide en français

**Version publiée actuelle :** [`0.3.3`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.3)

Portable Resume transfère un contexte local limité de Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen ou Kimi vers une session **neuve** d’agent de programmation. Il ne restaure ni processus ni session en cours. Les lecteurs restent hors ligne, utilisent uniquement la bibliothèque standard Python, n’exécutent jamais le CLI source et marquent le texte récupéré comme inerte et non fiable.

## Installation

Python 3.11+ est requis. Installez le paquet publié depuis PyPI :

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

Depuis un checkout, utilisez `pipx install .`. Pour installer les huit host de destination dans les emplacements utilisateur :

```bash
install-resume-skills quick-install all
```

Pour installer Qwen uniquement dans le projet courant :

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Les destinations sont Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code et Kimi Code CLI. Le [guide d’installation](../install-hosts.md) donne les commandes exactes pour Skill, extension, plugin et marketplace. Inspectez tout plugin et vérifiez le SHA-256 du release avant de lui faire confiance.

## Marketplace public

Le
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
public fournit une installation native pour six hosts compatibles :

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

Le guide contient les procédures vérifiées pour Cursor, Qwen, Grok et Kimi, ainsi que les solutions directes pour Antigravity et OpenCode.

## Vérification et utilisation

Dans le checkout :

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Activez `resume-<source>` selon la syntaxe du host et revérifiez le repository actuel avant d’appliquer le handoff.

Le smoke test a réussi 8/8 invocations de CLI et 7/7 installations locales de paquets natifs exacts. L’installation depuis le marketplace public a réussi sur 6/6 hosts compatibles ; les sélecteurs marketplace de Cursor et Kimi ont aussi réussi. Les autres sélecteurs visuels de Skill et les répertoires sélectionnés par les fournisseurs ne sont pas déclarés terminés.

Consultez l’[état du projet](../STATUS.md) pour distinguer les preuves vérifiées des étapes UI／release non exécutées.
