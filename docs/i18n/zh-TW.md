<!-- portable-resume-i18n: zh-TW v0.3.2 -->
# Portable Resume — 繁體中文快速指南

Portable Resume 可把 Claude、Codex、Cursor、OpenCode、Antigravity、Grok、Qwen、Kimi 的有限本機脈絡帶到**全新**的程式代理工作階段；它不是即時程序或工作階段還原。讀取器離線、僅使用 Python 標準函式庫、不會呼叫來源 CLI，並把復原文字標示為惰性且不受信任。

## 安裝

需要 Python 3.11+。從 PyPI 安裝已發布套件：

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

從原始碼 checkout 安裝可使用 `pipx install .`。一次安裝八個目的 host 到使用者全域路徑：

```bash
install-resume-skills quick-install all
```

只安裝目前專案的 Qwen：

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

支援的目的端為 Claude Code、Codex、Cursor、OpenCode、Antigravity、Grok Build、Qwen Code、Kimi Code CLI。每個 host 的直接 Skill、extension、plugin 與 marketplace 正確指令請見[安裝指南](../install-hosts.md)。信任第三方 plugin 前，請先檢查內容與 release SHA-256。

## 驗證與使用

在 checkout 中執行：

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

依目的 host 的語法啟用 `resume-<source>`，並在採取行動前重新確認目前 repository 狀態。

目前的本機 host 煙霧測試已通過 8/8 個 CLI 呼叫與 7/7 種支援的原生 plugin／extension 安裝。視覺化選擇器互動與公開 marketplace 發布仍是分開且尚未執行的證據項目。

已驗證項目與尚未執行的 UI／release 門檻請見[專案狀態](../STATUS.md)。
