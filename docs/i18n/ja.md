<!-- portable-resume-i18n: ja v0.4.2.dev0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — 日本語クイックスタート

**現在の公開版：** [`0.4.1`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.1)

Portable Resume は、Claude、Codex、Cursor、OpenCode、Antigravity、Grok、Qwen、Kimi の限定されたローカル文脈を**新しい**コーディングエージェントのセッションへ移行します。実行中プロセスやセッションの復元ではありません。リーダーはオフラインかつ Python 標準ライブラリのみで動作し、元の CLI を起動せず、復元テキストを不活性・未信頼として扱います。

## インストール

Python 3.11+ が必要です。PyPI から公開済みパッケージをインストールします：

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

<!-- portable-resume-current-registry:begin -->
現在の `main` checkout からは `pipx install .` を使えます。18 個の宛先 host をユーザー領域へまとめて導入：

```bash
install-resume-skills quick-install all
```

現在のプロジェクトだけに Qwen を導入：

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

`main` で有効な宛先は Antigravity / agy、Claude Code、Cline、Codex CLI / IDE、Crush、Cursor Agent、Gemini CLI、GitHub Copilot CLI、goose、Grok Build、Hermes Agent、Kilo CLI、Kimi Code CLI、OpenClaw、OpenCode、OpenHands、Pi agent、および Qwen Code です。
<!-- portable-resume-current-registry:end -->

公開済み `0.4.0` は Pi（ファイルシステム導入）を含む 9 宛先です（ネイティブ UI は not-run）。各 host の直接 Skill、extension、plugin、marketplace の正確な手順は[インストールガイド](../install-hosts.md)を参照してください。plugin を信頼する前に内容と release SHA-256 を確認します。

## 公開 marketplace

公開
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
は、互換性のある 6 host にネイティブな導入経路を提供します：

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

検証済みの Cursor、Qwen、Grok、Kimi 手順と、Antigravity／OpenCode の直接導入代替策はインストールガイドにあります。

## 検証と利用

checkout で実行：

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

宛先 host の構文で `resume-<source>` を有効化し、handoff に従う前に現在の repository を再確認してください。

現在の host スモークでは 8/8 の CLI 呼び出しと、正確なローカルパッケージ 7/7 の導入が成功しました。公開 marketplace 導入は互換性のある 6/6 host で成功し、Cursor と Kimi の marketplace picker も成功しています。その他の視覚的 Skill picker とベンダー選定ディレクトリは未申告です。

これらの host レベル結果は v0.3.2 時点の証拠です。v0.4.0 の host 別再インストールと picker フローは **not-run** のままです。
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.3.4-host-reinstall-not-run -->

検証済み事項と未実行の UI／release ゲートは[プロジェクト状況](../STATUS.md)を参照してください。
