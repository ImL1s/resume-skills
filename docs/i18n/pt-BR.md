<!-- portable-resume-i18n: pt-BR v0.4.0.dev0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — início rápido em português

**Versão publicada atual:** [`0.3.4`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.4)

Portable Resume migra contexto local limitado de Claude, Codex, Cursor, OpenCode, Antigravity, Grok, Qwen ou Kimi para uma sessão **nova** de agente de programação. Não restaura processos nem sessões em execução. Os leitores são offline, usam somente a biblioteca padrão do Python, nunca executam a CLI de origem e marcam o texto recuperado como inerte e não confiável.

## Instalação

Requer Python 3.11+. Instale o pacote publicado pelo PyPI:

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

Em um checkout do `main` atual, use `pipx install .`. Para instalar os 18 host de destino nos diretórios globais do usuário:

```bash
install-resume-skills quick-install all
```

Para instalar Qwen apenas no projeto atual:

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

Os destinos habilitados no `main` são Antigravity / agy, Claude Code, Cline, Codex CLI / IDE, Crush, Cursor Agent, Gemini CLI, GitHub Copilot CLI, goose, Grok Build, Hermes Agent, Kilo CLI, Kimi Code CLI, OpenClaw, OpenCode, OpenHands, Pi agent e Qwen Code. O `0.3.4` publicado inclui nove destinos com Pi (instalação de arquivos; UI nativa not-run). A [documentação de instalação](../install-hosts.md) contém os comandos exatos de Skill, extension, plugin e marketplace. Inspecione qualquer plugin e confira o SHA-256 do release antes de confiar nele.

## Marketplace público

O
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
público oferece instalação nativa para seis hosts compatíveis:

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

O guia contém as rotas verificadas para Cursor, Qwen, Grok e Kimi, além das alternativas diretas para Antigravity e OpenCode.

## Verificação e uso

No checkout:

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

Ative `resume-<source>` pela sintaxe do host e verifique novamente o repository atual antes de agir sobre o handoff.

O smoke de hosts passou em 8/8 invocações de CLI e 7/7 instalações locais de pacotes nativos exatos. A instalação pelo marketplace público passou em 6/6 hosts compatíveis; os seletores de marketplace do Cursor e Kimi também passaram. Os demais seletores visuais de Skill e diretórios selecionados pelos fornecedores não são declarados concluídos.

Esses resultados por host são evidências da v0.3.2. A reinstalação host a host e os fluxos de seletor da v0.3.4 continuam **not-run**.
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.3.4-host-reinstall-not-run -->

Consulte o [status do projeto](../STATUS.md) para separar evidências verificadas de etapas UI／release ainda não executadas.
