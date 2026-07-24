<!-- portable-resume-i18n: es v0.3.2 -->
# Portable Resume — inicio rápido en español

**Versión publicada actual:** [`0.3.2`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2)

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

## Verificación y uso

En el checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Active `resume-<source>` con la sintaxis documentada del host y vuelva a comprobar el repository actual antes de actuar.

La prueba local de hosts superó 8/8 invocaciones de CLI; los paquetes exactos `0.3.2` superaron 7/7 instalaciones nativas de plugin／extension admitidas. La interacción con selectores visuales y la publicación en marketplaces públicos siguen siendo comprobaciones separadas no ejecutadas.

Consulte el [estado del proyecto](../STATUS.md) para distinguir pruebas verificadas de puertas UI／release aún no ejecutadas.
