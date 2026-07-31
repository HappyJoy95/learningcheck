# README 部署手册 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 README 改写成 Windows 运维人员可独立执行的从零部署手册。

**Architecture:** 只修改现有 README，遵循“准备条件 → 安装 → 配置 → 验收 → 定时任务 → 运维”的线性操作路径。内容以项目当前脚本、配置模板和实际运行行为为唯一事实来源，不展示真实凭据。

**Tech Stack:** Markdown、Windows 批处理、PowerShell、Python、ADB、安卓模拟器。

---

### Task 1: 编写部署与配置说明

**Files:**
- Modify: `README.md`
- Reference: `config/config.json.example`
- Reference: `config/general.yaml.example`
- Reference: `schedule_setup.ps1`
- Reference: `modules/account_source.py`
- Reference: `modules/task.py`

- [ ] **Step 1: 将 README 重组为运维操作顺序**

写入以下顺序的章节：项目用途、Windows 前置条件、从零部署、配置项目、账号 CSV、首次运行、输出、定时任务、日常运维、安全要求与故障排查。

- [ ] **Step 2: 写入可执行的配置与验收细节**

提供脱敏 CSV 示例：`username,password,account_type,user_name,execute_flag,store_name,remark`。提供 `adb devices`、切换至项目目录和 `run.bat` 的命令。明确 `execute_flag=1` 表示待执行，成功账号会变为 `0`；说明 `schedule_setup.ps1` 当前创建每天 08:00 的 Windows 任务，调整时间须修改脚本中的 `-At "08:00"` 后重新安装任务。

- [ ] **Step 3: 写入风险和故障排查**

覆盖 Python 或依赖未安装、ADB 无设备、模拟器分辨率或 App 版本变化、账号 CSV 表头错误、邮件授权失败、OCR 首次下载失败、邮件或 HTTP 上传失败。说明报告位于 `data/learning_check/<运行时间>/`，上传使用 HTTP 时仅应在可信网络启用。

- [ ] **Step 4: 审校 README 的事实与安全性**

用 `findstr /I /N "your_email@example.com your_smtp_auth_code your_owner_key" README.md` 检查，确认只包含模板占位文本，且没有任何现有账号、密码、授权码、主机名或密钥。

- [ ] **Step 5: 审校文档结构**

用 `findstr /R /N "^## " README.md` 检查，确认依次包含部署、首次验收和故障排查章节。

- [ ] **Step 6: 提交文档改动**

执行 `git add README.md` 与 `git commit -m "docs: expand Windows deployment guide"`。
