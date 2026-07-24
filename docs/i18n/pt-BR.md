<!-- portable-resume-i18n: pt-BR v0.3.0 -->
# Portable Resume — início rápido em português

Portable Resume migra contexto local limitado de Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen ou Kimi para uma sessão **nova** de agente de programação. Não restaura processos nem sessões em execução. Os leitores são offline, usam somente a biblioteca padrão do Python, nunca executam a CLI de origem e marcam o texto recuperado como inerte e não confiável.

## Instalação

Requer Python 3.11+. Após a publicação no PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

Em um checkout, use `pipx install .`. Para instalar os oito host de destino nos diretórios globais do usuário:

```bash
install-resume-skills quick-install all
```

Para instalar Qwen apenas no projeto atual:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Os destinos são Claude Code, Codex, Cursor, OpenCode, Antigravity, Grok Build, Qwen Code e Kimi Code CLI. A [documentação de instalação](../install-hosts.md) contém os comandos exatos de Skill, extension, plugin e marketplace. Inspecione qualquer plugin e confira o SHA-256 do release antes de confiar nele.

## Verificação e uso

No checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Ative `resume-<source>` pela sintaxe do host e verifique novamente o repository atual antes de agir sobre o handoff.

Busca web e Context7 opcionais estão em [integrações de rede](../network-integrations.md); o leitor continua offline. Consulte o [status do projeto](../STATUS.md) para separar evidências verificadas de etapas UI／release ainda não executadas.
