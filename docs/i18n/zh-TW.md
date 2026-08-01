<!-- portable-resume-i18n: zh-TW v0.4.1.dev0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — 繁體中文快速指南

**目前已發布版本：** [`0.4.0`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.0)

Portable Resume 可把 Claude、Codex、Cursor、OpenCode、Antigravity、Grok、Qwen、Kimi 的有限本機脈絡帶到**全新**的程式代理工作階段；它不是即時程序或工作階段還原。讀取器離線、僅使用 Python 標準函式庫、不會呼叫來源 CLI，並把復原文字標示為惰性且不受信任。

## 安裝

需要 Python 3.11+。從 PyPI 安裝已發布套件：

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

<!-- portable-resume-current-registry:begin -->
從原始碼 checkout（目前 `main`）安裝可使用 `pipx install .`。一次安裝 18 個目的 host 到使用者全域路徑：

```bash
install-resume-skills quick-install all
```

只安裝目前專案的 Qwen：

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

`main` 上啟用的目的端為 Antigravity / agy、Claude Code、Cline、Codex CLI / IDE、Crush、Cursor Agent、Gemini CLI、GitHub Copilot CLI、goose、Grok Build、Hermes Agent、Kilo CLI、Kimi Code CLI、OpenClaw、OpenCode、OpenHands、Pi agent，以及 Qwen Code。
<!-- portable-resume-current-registry:end -->

已發布的 `0.4.0` 含九個目的端（含 Pi 檔案系統安裝；原生 UI 仍為 not-run）。每個 host 的直接 Skill、extension、plugin 與 marketplace 正確指令請見[安裝指南](../install-hosts.md)。信任第三方 plugin 前，請先檢查內容與 release SHA-256。

## 公開 marketplace

公開的
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
提供六個相容 host 的原生安裝方式：

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

Cursor、Qwen、Grok、Kimi 的已驗證指令，以及 Antigravity／OpenCode 的直接安裝替代方案，請見安裝指南。

## 驗證與使用

在 checkout 中執行：

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

依目的 host 的語法啟用 `resume-<source>`，並在採取行動前重新確認目前 repository 狀態。

目前 host 煙霧測試已通過 8/8 個 CLI 呼叫與 7/7 種精確的本機原生套件安裝。公開 marketplace 安裝已通過 6/6 個相容 host，Cursor 與 Kimi 的 marketplace 選擇器也已通過。其他視覺化 Skill 選擇器與廠商精選目錄仍未宣稱完成。

這些 host 層級結果屬於 v0.3.2 時期證據；v0.4.0 的逐 host 重新安裝與 picker 流程仍為 **not-run**。
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.3.4-host-reinstall-not-run -->

已驗證項目與尚未執行的 UI／release 門檻請見[專案狀態](../STATUS.md)。
