# 学习检查自动化（Windows 部署手册）

本项目面向 Windows 运维人员：通过 ADB 控制安卓模拟器中的华为零售通，批量检查学习任务、截图并使用 OCR 判断完成状态，生成本地报告；可选发送邮件或上传报告。

## 1. 项目用途与运行边界

- 运行入口是 `main.py`；日常手动运行使用 `run.bat`，安装依赖可使用 `install.bat`。
- 项目会自动操作模拟器内的应用界面。首次上线必须有人值守，确认模拟器分辨率、App 版本、账号权限和网络符合业务要求。
- 项目不负责账号开通、密码找回、模拟器或应用安装。
- 不要将真实账号、密码、邮箱授权码、上传密钥或内部地址提交到代码仓库、工单或聊天记录。

## 2. 部署前准备

准备一台可持续运行的 Windows 10/11 电脑，并满足：

- Python 3.8 或更高版本；安装 Python 时勾选 **Add Python to PATH**。
- 已安装 ADB，且命令提示符可直接执行 `adb`。
- 已安装并启动 MuMu、夜神或其他支持 ADB 的安卓模拟器。
- 模拟器中已安装并可手动登录华为零售通。
- 对项目目录和账号文件具有受控读写权限。
- 使用 OCR 时预留网络、磁盘和内存；PaddleOCR 首次运行会下载约 100 MB 模型。

下文以 `C:\Apps\learningcheck` 作为项目目录示例；请替换为实际路径。

## 3. 从零部署

所有命令默认在 **命令提示符（cmd）** 执行。

### 3.1 检查 Python

```bat
cd /d C:\Apps\learningcheck
py --version
```

应显示 Python 3.8 或更高版本。若没有 `py` 命令，可改用：

```bat
python --version
```

### 3.2 安装依赖

```bat
cd /d C:\Apps\learningcheck
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
```

也可以运行项目自带脚本：

```bat
cd /d C:\Apps\learningcheck
install.bat
```

若系统只提供 `python`，将命令中的 `py` 替换为 `python`。

### 3.3 配置 ADB 与模拟器

将 ADB 所在目录加入 Windows 的 `Path` 环境变量，重新打开命令提示符后执行：

```bat
adb version
adb devices
```

启动模拟器并开启其 ADB 调试，再按实际地址连接。例如 MuMu 常见地址为：

```bat
adb connect 127.0.0.1:16384
adb devices
```

输出中必须出现**唯一且预期的**模拟器地址，状态为 `device`；先断开遗留设备，避免任务操作错误目标。将同一地址写入 `config\config.json` 的 `adb_port`：

```json
{
  "adb_port": "127.0.0.1:16384"
}
```

示例地址仅作说明，请以本机模拟器实际端口为准。

### 3.4 创建并编辑配置

```bat
cd /d C:\Apps\learningcheck
copy config\config.json.example config\config.json
copy config\general.yaml.example config\general.yaml
notepad config\config.json
notepad config\general.yaml
```

至少检查以下项目：

- `config.json`：`adb_port`、账号来源、通知和上传开关。应用包名/启动页通常保留模板默认值。
- `general.yaml`：SMTP 发件配置。若不使用邮件，应在 `config.json` 中关闭邮件通知和邮件账号源。
- Windows 定时任务由 `schedule_setup.ps1` 管理；该脚本当前固定每天 08:00 触发。

## 4. 配置账号与可选服务

### 4.1 本地账号 CSV

```bat
cd /d C:\Apps\learningcheck
mkdir data\learning_check\input
notepad data\learning_check\input\accounts.csv
```

CSV 必填列为 `username,password,account_type,user_name,store_name`。建议使用完整表头：

```csv
username,password,account_type,user_name,execute_flag,store_name,remark
demo_user_001,replace_with_password,个人消费,示例员工,1,示例门店,仅示例数据
```

- 用已获授权的真实业务数据替换示例，绝不提交该文件。
- `execute_flag=1` 表示待执行，`0` 表示跳过。
- 文件必须是 CSV，首行必须为表头；推荐 UTF-8（带 BOM）编码，程序也会尝试 UTF-8 和 GBK。

### 4.2 从邮件刷新账号（可选）

当 `account_source.mode` 为 `mail_then_local` 或 `mail`，且 `account_source.mail.enabled` 为 `true` 时，程序会从 IMAP 邮箱查找名为 `accounts.csv` 的附件。成功获取有效附件后，会整份覆盖本机 `accounts.csv`，附件中的账号、密码和 `execute_flag` 都是本次执行依据；未获取到附件时，才按配置使用本机上一次保存的账号文件及其 flag。

推荐用环境变量提供邮箱凭据：

```bat
set LEARNING_CHECK_IMAP_EMAIL=your_mailbox@example.com
set LEARNING_CHECK_IMAP_AUTH_CODE=replace_with_authorization_code
run.bat
```

上面的 `set` 只对当前命令窗口有效，适合首次手动验证。长期运行时，应使用组织的凭据管理或 Windows 环境变量策略安全下发，并确保变量在**计划任务运行的同一 Windows 用户上下文**中可读；不要用明文 `setx` 保存授权码。安装计划任务后请手动触发一次，验证邮件取数确实可用。程序也会回退尝试 `SMTP_USER` / `SMTP_PASSWORD`，再尝试 `config/general.yaml` 中的 SMTP 配置。

### 4.3 邮件通知与 HTTP 上传（可选）

邮件通知需同时满足：`general.yaml` 中的 SMTP 配置可用；`notify_enabled` 为 `true`；`notify_type` 包含 `email`；以及已填写 `notify_email_target`。ZIP 附件大于 50 MB 时只发送正文。

上传由 `config.json` 的 `upload` 控制，启用时需要 `mcp_host`、`mcp_port` 和 `remote_path`，并按服务要求配置 `owner_key`。上传接口使用 **HTTP**，不提供传输加密；禁止经公网、公共 Wi-Fi 或未受控 VPN 使用。仅可在受防火墙和访问控制保护的可信网络中启用，并应在上线前取得安全审批；服务支持时优先使用 HTTPS。不需要时设置：

```json
{ "upload": { "enabled": false } }
```

模板含企业微信字段，但独立入口当前只实现邮件发送；不要仅凭字段存在推断其他通知通道可用。

## 5. 首次运行与验收

首次部署请保持模拟器已启动、ADB 已连接，并有人观察整个过程：

```bat
cd /d C:\Apps\learningcheck
run.bat
```

也可直接运行：

```bat
py main.py
```

控制台出现 `任务完成:`、`成功: True` 和报告路径，表示程序已按自身逻辑完成。仍须检查模拟器实际操作，以及报告中的失败账号、未完成账号和通知/上传结果；不能只依赖进程退出。

每次运行会创建：

```text
data\learning_check\<运行时间>\
```

常见产物：

- `execution_report.json`：执行汇总和账号结果。
- `ocr_results.json`：OCR 分析结果。
- `result.json`：账号结果及汇总。
- `failed_accounts.txt`：失败账号摘要（如有）。
- `uncompleted_accounts.csv`：未完成账号名单（如有）。
- `screenshots_<时间>.zip`：报告与截图压缩包。

成功打包后，未压缩的 `screenshots` 目录会被删除，但 ZIP 会保留。运行中的 `accounts_used.csv` 包含密码，成功结束时会清理；仍应限制整个 `data` 目录访问权限。

## 6. 配置 Windows 定时任务

`schedule_setup.ps1` 会创建名为 `LearningCheck-Auto` 的任务，每天 **08:00** 运行项目根目录的 `run.bat`。脚本要求管理员权限，并以当前交互用户身份运行。

### 安装

以管理员身份打开 PowerShell：

```powershell
cd C:\Apps\learningcheck
powershell -ExecutionPolicy Bypass -File .\schedule_setup.ps1
```

脚本会询问是否立即测试；首次建议输入 `y`，再查看报告目录。

### 验证与手动触发

```bat
schtasks /Query /TN "LearningCheck-Auto" /V /FO LIST
schtasks /Run /TN "LearningCheck-Auto"
```

也可运行 `taskschd.msc`，检查同名任务的触发器、上次运行结果及操作路径。

### 修改时间或删除任务

推荐在 `taskschd.msc` 中编辑：`LearningCheck-Auto` → **属性** → **触发器**。如需修改脚本预设时间，编辑 `schedule_setup.ps1` 中的 `-At "08:00"` 后，以管理员身份重新运行该脚本；它会替换同名旧任务。

删除任务：

```bat
schtasks /Delete /TN "LearningCheck-Auto" /F
```

这不会删除项目文件或既有报告。

## 7. 日常运维与安全

程序只处理 `execute_flag=1` 的有效账号。判定已完成的账号会被写为 `0`；未完成、登录失败或其他失败的账号会保留待处理。每个自然周首次运行时，程序会将当前 `accounts.csv` 的 flag 重置为 `1`，再按当次结果更新。后续运行中，若收到邮件附件，则以附件中维护的 flag 为准；若未收到附件，则保留本机上次运行后的 flag，仅执行仍为 `1` 的账号。

因此，`0` 不是永久停用标记。要永久排除账号，只需在后续邮件附件中移除该账号，或将其 `execute_flag` 设为 `0`；附件成功获取后会覆盖本机缓存。若邮件暂时获取失败但需立即停用，可在本机缓存中先将该账号设为 `0`。

- 将 `config/config.json`、`config/general.yaml` 和账号 CSV 视为敏感文件，限制 NTFS 权限并备份到受控位置。
- 使用专用、最小权限、可撤销的服务账号；泄露疑虑或人员变动时立即轮换。
- 不要在报告、截图、日志、邮件转发或上传目录中扩散凭据。
- 仅连接受信任的模拟器和 ADB 端口，避免暴露 ADB 或 HTTP 上传服务到不受控网络；HTTP 上传端点应受防火墙和访问控制保护。

## 8. 常见故障排查

### 找不到 Python 或 pip

重新安装 Python 并勾选加入 PATH，重新打开命令提示符：

```bat
py --version
py -m pip --version
```

### 找不到 ADB 或没有设备

确认 ADB 已加入 Path，检查模拟器端口：

```bat
adb kill-server
adb start-server
adb connect 127.0.0.1:实际端口
adb devices
```

`offline` 时重启模拟器后重连；端口不确定时到模拟器开发者/ADB 设置中确认，并同步更新 `config.json`。

### App 无法启动或界面操作失败

确认模拟器与应用可手动打开；检查 `app_package`、`app_activity` 和 `adb_port`。项目依赖界面元素与坐标，模拟器分辨率或 App 版本变化后应先人工观察一次完整运行。

### 账号文件不存在、列缺失或无可执行账号

确认文件为 `data\learning_check\input\accounts.csv`，表头包含 `username,password,account_type,user_name,store_name`，至少一行有效账号的 `execute_flag` 是 `1`。启用邮件源时同时检查 IMAP 凭据、附件名和本地回退文件。

### OCR 下载慢、失败或识别异常

首次模型下载约 100 MB，检查网络、磁盘和内存后重试。临时关闭 OCR 可将 `automation.ocr_enabled` 和当天策略的 `ocr_enabled` 设为 `false`；这会改变完成状态判定，恢复前应人工核验。

### 邮件、上传或计划任务失败

邮件和上传先核对开关、必填配置、网络、防火墙和授权；不需要 HTTP 上传时关闭 `upload.enabled`。计划任务则检查电脑开机、创建任务的交互用户已登录、模拟器可用，并执行 `schtasks /Query /TN "LearningCheck-Auto" /V /FO LIST` 查看上次运行结果；必要时手动触发一次并检查报告目录。
