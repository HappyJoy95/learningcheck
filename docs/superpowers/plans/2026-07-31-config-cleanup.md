# 独立运行配置精简 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除未接入的外部平台配置，并使模板和 README 仅描述独立运行支持的配置。

**Architecture:** 配置模板仅保留代码读取的字段；删除没有读取点的表单元数据和调度文件。README 作为唯一运维配置说明，同步去除已删除文件的引用。

**Tech Stack:** JSON、YAML、Markdown、Python 标准库。

---

### Task 1: 精简独立运行配置

**Files:**
- Modify: `config/config.json.example`
- Modify: `config/general.yaml.example`
- Modify: `README.md`
- Delete: `config/config.yaml`
- Delete: `config/settings.yaml`
- Delete: `config/meta.yaml`

- [ ] 删除 `config/settings.yaml`、`config/meta.yaml` 和 `config/config.yaml`。
- [ ] 将 `config/config.json.example` 保留为 ADB、应用启动、邮件账号源、OCR、邮件通知和 HTTP 上传字段；删除未读取的模拟器、测试、周策略、保留策略和企业微信字段。
- [ ] 将 `config/general.yaml.example` 保留为 `smtp_server`、`smtp_port`、`smtp_user` 与 `smtp_password`。
- [ ] 删除 README 中对 `config/config.yaml` 的说明，明确定时运行由 `schedule_setup.ps1` 管理。
- [ ] 使用 `rg` 确认 README 不再引用被删除文件；运行 `PYTHONPYCACHEPREFIX=/private/tmp/learningcheck-pycache python3 -m compileall -q main.py modules`，预期无输出且退出码为 0。
