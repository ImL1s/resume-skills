<!-- portable-resume-i18n: zh-CN v0.3.2 -->
# Portable Resume — 简体中文快速指南

**当前已发布版本：** [`0.3.2`](https://github.com/ImL1s/resume-skills/releases/tag/v0.3.2)

Portable Resume 可将 Claude、Codex、Cursor、OpenCode、Antigravity、Grok、Qwen、Kimi 的有限本地上下文迁移到**全新**的编程代理会话；它不是实时进程或会话恢复。读取器离线、仅使用 Python 标准库、不会调用来源 CLI，并将恢复内容标记为惰性且不受信任。

## 安装

需要 Python 3.11+。从 PyPI 安装已发布的软件包：

```bash
pipx install portable-resume
install-resume-skills quick-install qwen
```

从源码 checkout 安装可运行 `pipx install .`。一次安装八个目标 host 到用户全局目录：

```bash
install-resume-skills quick-install all
```

仅为当前项目安装 Qwen：

```bash
install-resume-skills quick-install qwen --project "$PWD"
```

支持的目标端包括 Claude Code、Codex、Cursor、OpenCode、Antigravity、Grok Build、Qwen Code 和 Kimi Code CLI。各 host 的直接 Skill、extension、plugin 与 marketplace 命令见[安装指南](../install-hosts.md)。信任第三方 plugin 前，请检查内容并核对 release SHA-256。

## 验证与使用

在 checkout 中运行：

```bash
python3 scripts/self_verify.py
python3 scripts/check_secrets.py
PYTHONPATH=src python3 scripts/smoke_installed_matrix.py
```

按目标 host 的语法启用 `resume-<source>`，并在执行交接内容前重新检查当前 repository。

当前本地 host 冒烟测试已通过 8/8 个 CLI 调用；精确的 `0.3.2` 软件包已通过 7/7 种支持的原生 plugin／extension 安装。可视化选择器交互与公开 marketplace 发布仍是分开且尚未执行的证据项目。

已验证项目与尚未执行的 UI／release 门槛见[项目状态](../STATUS.md)。
