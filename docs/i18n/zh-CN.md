<!-- portable-resume-i18n: zh-CN v0.4.2.dev0 -->
<!-- portable-resume-counts: sources=17 destinations=18 -->
# Portable Resume — 简体中文快速指南

**当前已发布版本：** [`0.4.1`](https://github.com/ImL1s/resume-skills/releases/tag/v0.4.1)

Portable Resume 可将 Claude、Codex、Cursor、OpenCode、Antigravity、Grok、Qwen、Kimi 的有限本地上下文迁移到**全新**的编程代理会话；它不是实时进程或会话恢复。读取器离线、仅使用 Python 标准库、不会调用来源 CLI，并将恢复内容标记为惰性且不受信任。

## 安装

需要 Python 3.11+。从 PyPI 安装已发布的软件包：

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

<!-- portable-resume-current-registry:begin -->
从当前 `main` 源码 checkout 安装可运行 `pipx install .`。一次安装 18 个目标 host 到用户全局目录：

```bash
install-resume-skills quick-install all
```

仅为当前项目安装 Qwen：

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

`main` 上启用的目标端包括 Antigravity / agy、Claude Code、Cline、Codex CLI / IDE、Crush、Cursor Agent、Gemini CLI、GitHub Copilot CLI、goose、Grok Build、Hermes Agent、Kilo CLI、Kimi Code CLI、OpenClaw、OpenCode、OpenHands、Pi agent，以及 Qwen Code。
<!-- portable-resume-current-registry:end -->

已发布的 `0.4.0` 含九个目标端（含 Pi 文件系统安装；原生 UI 仍为 not-run）。各 host 的直接 Skill、extension、plugin 与 marketplace 命令见[安装指南](../install-hosts.md)。信任第三方 plugin 前，请检查内容并核对 release SHA-256。

## 公开 marketplace

公开的
[`portable-resume-marketplace`](https://github.com/ImL1s/portable-resume-marketplace)
为六个兼容 host 提供原生安装方式：

```bash
claude plugin marketplace add ImL1s/portable-resume-marketplace
claude plugin install portable-resume@portable-resume --scope user
codex plugin marketplace add ImL1s/portable-resume-marketplace
codex plugin add portable-resume@portable-resume
```

Cursor、Qwen、Grok、Kimi 的已验证命令以及 Antigravity／OpenCode 的直接安装替代方案见安装指南。

## 验证与使用

在 checkout 中运行：

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

按目标 host 的语法启用 `resume-<source>`，并在执行交接内容前重新检查当前 repository。

当前 host 冒烟测试已通过 8/8 个 CLI 调用和 7/7 种精确的本地原生软件包安装。公开 marketplace 安装已通过 6/6 个兼容 host，Cursor 与 Kimi 的 marketplace 选择器也已通过。其他可视化 Skill 选择器与厂商精选目录仍未声明完成。

这些 host 级结果属于 v0.3.2 时期证据；v0.4.0 的逐 host 重新安装与 picker 流程仍为 **not-run**。
<!-- portable-resume-evidence-scope: v0.3.2-hosts v0.3.4-host-reinstall-not-run -->

已验证项目与尚未执行的 UI／release 门槛见[项目状态](../STATUS.md)。
