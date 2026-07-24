<!-- portable-resume-i18n: es v0.3.0 -->
# Portable Resume — inicio rápido en español

Portable Resume migra contexto local limitado de Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen o Kimi a una sesión **nueva** de un agente de programación. No restaura procesos ni sesiones en vivo. Los lectores funcionan sin red, usan solo la biblioteca estándar de Python, nunca ejecutan el CLI de origen y marcan el texto recuperado como inerte y no confiable.

## Instalación

Requiere Python 3.11+. Después de publicarse en PyPI:

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

## Verificación y uso

En el checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Active `resume-<source>` con la sintaxis documentada del host y vuelva a comprobar el repository actual antes de actuar.

La búsqueda web y Context7 opcionales se describen en [integraciones de red](../network-integrations.md); el lector permanece sin conexión. Consulte el [estado del proyecto](../STATUS.md) para distinguir pruebas verificadas de puertas UI／release aún no ejecutadas.
