<!-- portable-resume-i18n: es v0.4.0.dev0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — inicio rápido en español

**Versión publicada actual:** [`0.3.4`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.4)

Portable Resume migra contexto local limitado de Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen o Kimi a una sesión **nueva** de un agente de programación. No restaura procesos ni sesiones en vivo. Los lectores funcionan sin red, usan solo la biblioteca estándar de Python, nunca ejecutan el CLI de origen y marcan el texto recuperado como inerte y no confiable.

## Instalación

Requiere Python 3.11+. Instale el paquete publicado desde PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

Desde un checkout de `main` actual use `pipx install .`. Para instalar los 18 host de destino en rutas globales del usuario:

```bash
install-resume-skills quick-install all
```

Para instalar Qwen solo en el proyecto actual:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Los destinos habilitados en `main` son Antigravity / agy, Claude Code, Cline, Codex CLI / IDE, Crush, Cursor Agent, Gemini CLI, GitHub Copilot CLI, goose, Grok Build, Hermes Agent, Kilo CLI, Kimi Code CLI, OpenClaw, OpenCode, OpenHands, Pi agent y Qwen Code. El `0.3.4` publicado incluye nueve destinos con Pi (instalación de archivos; UI nativa not-run). Consulte la [guía de instalación](../install-hosts.md) para los comandos exactos de Skill, extension, plugin y marketplace. Revise cualquier plugin y verifique el SHA-256 del release antes de confiar en él.

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

Estos resultados por host corresponden a evidencia de v0.3.2. La reinstalación host por host y los flujos de selector de v0.3.4 siguen **not-run**.
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.3.4-host-reinstall-not-run -->

Consulte el [estado del proyecto](../STATUS.md) para distinguir pruebas verificadas de puertas UI／release aún no ejecutadas.
