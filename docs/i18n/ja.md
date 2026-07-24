<!-- portable-resume-i18n: ja v0.3.0 -->
# Portable Resume — 日本語クイックスタート

Portable Resume は、Claude、Codex、Cursor、OpenCode、Antigravity、Grok、Qwen、Kimi の限定されたローカル文脈を**新しい**コーディングエージェントのセッションへ移行します。実行中プロセスやセッションの復元ではありません。リーダーはオフラインかつ Python 標準ライブラリのみで動作し、元の CLI を起動せず、復元テキストを不活性・未信頼として扱います。

## インストール

Python 3.11+ が必要です。PyPI から公開済みパッケージをインストールします：

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

checkout からは `pipx install .` を使えます。8 個の宛先 host をユーザー領域へまとめて導入：

```bash
install-resume-skills quick-install all
```

現在のプロジェクトだけに Qwen を導入：

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

宛先は Claude Code、Codex、Cursor、OpenCode、Antigravity、Grok Build、Qwen Code、Kimi Code CLI です。各 host の直接 Skill、extension、plugin、marketplace の正確な手順は[インストールガイド](../install-hosts.md)を参照してください。plugin を信頼する前に内容と release SHA-256 を確認します。

## 検証と利用

checkout で実行：

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

宛先 host の構文で `resume-<source>` を有効化し、handoff に従う前に現在の repository を再確認してください。

任意の Web 検索と Context7 は[ネットワーク連携](../network-integrations.md)に記載されています。リーダー自体は常にオフラインです。検証済み事項と未実行の UI／release ゲートは[プロジェクト状況](../STATUS.md)を参照してください。
