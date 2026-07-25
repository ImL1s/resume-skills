<!-- portable-resume-i18n: es v0.3.3 -->
# Portable Resume — inicio rápido en español

**Versión publicada actual:** [`0.3.3`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.3)

Portable Resume migra contexto local limitado de Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen o Kimi a una sesión **nueva** de un agente de programación. No restaura procesos ni sesiones en vivo. Los lectores funcionan sin red, usan solo la biblioteca estándar de Python, nunca ejecutan el CLI de origen y marcan el texto recuperado como inerte y no confiable.

## Instalación

Requiere Python 3.11+. Instale el paquete publicado desde PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

Desde un checkout use `pipx install .`. Para instalar los ocho host de destino en rutas globales del usuario:

```bash
install-resume-skills quick-install all
```

Para instalar Qwen solo en el proyecto actual:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Los destinos son Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code y Kimi Code CLI. Consulte la [guía de instalación](../install-hosts.md) para los comandos exactos de Skill, extension, plugin y marketplace. Revise cualquier plugin y verifique el SHA-256 del release antes de confiar en él.

## Marketplace público

El
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
público ofrece instalación nativa para seis hosts compatibles:

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

La guía contiene las rutas verificadas para Cursor, Qwen, Grok y Kimi, además de las alternativas directas para Antigravity y OpenCode.

## Verificación y uso

En el checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Active `resume-<source>` con la sintaxis documentada del host y vuelva a comprobar el repository actual antes de actuar.

La prueba de hosts superó 8/8 invocaciones de CLI y 7/7 instalaciones locales de paquetes nativos exactos. La instalación desde el marketplace público superó 6/6 hosts compatibles; también pasaron los selectores de marketplace de Cursor y Kimi. No se declaran completados los demás selectores visuales de Skill ni los directorios seleccionados por proveedores.

Consulte el [estado del proyecto](../STATUS.md) para distinguir pruebas verificadas de puertas UI／release aún no ejecutadas.
