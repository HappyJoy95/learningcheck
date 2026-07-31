# 独立运行配置精简设计

## 目标

移除学习检查独立运行入口未读取的配置字段和外部平台元数据，仅保留当前 Python 代码、Windows 计划任务和 README 实际需要的内容。

## 范围

- 删除 `config/settings.yaml` 与 `config/meta.yaml`。
- 精简 `config/config.json.example`：保留 ADB、应用启动、账号邮件源、OCR、邮件通知和 HTTP 上传的已读取字段；删除模拟器路径、测试模式、未接入的重试策略、保留策略与企业微信字段。
- 精简 `config/general.yaml.example`：只保留 SMTP 字段。
- 删除 `config/config.yaml`，因为独立运行入口及 Windows 计划任务均不读取它。
- 更新 README，移除已删除配置文件的说明，并明确 Windows 定时任务只由 `schedule_setup.ps1` 管理。

## 保留的业务规则

邮件附件成功时整份覆盖本机账号表，附件中的账号、密码和 `execute_flag` 生效；邮件失败时使用本机缓存。每个自然周首次运行将当前账号表的 flag 重置为 `1`，随后按执行结果回写。

## 验收

模板中的每个字段均能在独立运行 Python 代码或 Windows 计划任务脚本中找到读取点；README 不再引用删除的配置文件；Python 语法检查通过。
