<!-- portable-resume-i18n: fr v0.3.0 -->
# Portable Resume — démarrage rapide en français

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

## Vérification et utilisation

Dans le checkout :

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Activez `resume-<source>` selon la syntaxe du host et revérifiez le repository actuel avant d’appliquer le handoff.

La recherche Web et Context7 facultatives sont décrites dans les [intégrations réseau](../network-integrations.md) ; le lecteur reste hors ligne. Consultez l’[état du projet](../STATUS.md) pour distinguer les preuves vérifiées des étapes UI／release non exécutées.
