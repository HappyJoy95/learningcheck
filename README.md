# 学习检查自动化

通过 ADB 控制安卓模拟器，自动完成华为学习晨读/大练兵的截图与 OCR 检查。

## 功能

- 自动登录华为零售通 APP
- 执行学习任务并截图
- OCR 识别截图内容，检测未完成项
- 生成检查报告（Markdown + CSV）
- 支持邮件/企业微信通知
- 支持从邮件获取账号列表

## 环境要求

- Windows 10/11
- Python 3.8+
- ADB（加入 PATH）
- 安卓模拟器（MuMu、夜神等）

## 快速开始

### 1. 安装依赖

```bat
pip install -r requirements.txt
```

或运行 `install.bat`。

### 2. 配置

```bash
cp config/config.json.example config/config.json
cp config/general.yaml.example config/general.yaml
```

编辑配置文件，填入：
- ADB 端口（模拟器地址）
- 邮件服务器信息（可选）
- 企业微信/邮件通知（可选）

### 3. 准备账号文件

将 `accounts.csv` 放入 `data/learning_check/input/` 目录：

```csv
username,password,account_type,user_name,execute_flag,store_name,remark
账号,密码,个人消费,张三,1,XX门店,
```

### 4. 运行

```bat
run.bat
```

或：

```bash
python main.py
```

## 配置说明

### ADB 端口

| 模拟器 | 地址 |
|--------|------|
| MuMu | `127.0.0.1:16384` |
| 夜神 | `127.0.0.1:62001` |

### 邮件获取账号

在 `config/config.json` 中启用：

```json
{
  "account_source": {
    "mode": "mail_then_local",
    "mail": {
      "enabled": true
    }
  }
}
```

凭据优先级：
1. 环境变量 `LEARNING_CHECK_IMAP_EMAIL` / `LEARNING_CHECK_IMAP_AUTH_CODE`
2. 环境变量 `SMTP_USER` / `SMTP_PASSWORD`
3. `config/general.yaml` 中的 `smtp_user` / `smtp_password`

### OCR

依赖 PaddleOCR，首次运行自动下载模型（约 100MB）。如不需要可在配置中关闭：

```json
{
  "automation": {
    "ocr_enabled": false
  }
}
```

## 目录结构

```
learningcheck/
├── main.py              # 入口文件
├── run.bat              # 启动脚本
├── install.bat          # 依赖安装脚本
├── requirements.txt     # Python 依赖
├── config/
│   ├── config.json      # 任务配置（从 .example 复制）
│   ├── config.yaml      # 调度配置
│   ├── settings.yaml    # 前端设置表单
│   ├── meta.yaml        # 模块元数据
│   └── general.yaml     # 通用配置（从 .example 复制）
├── modules/
│   ├── base.py          # 任务基类
│   ├── task.py          # 主任务
│   ├── account_source.py # 账号源（本地/邮件）
│   ├── ocr.py           # OCR 识别
│   ├── report.py        # 报告生成
│   ├── workflow.py      # 自动化流程
│   ├── upload.py        # 结果上传
│   └── modules/
│       ├── adb_manager.py   # ADB 管理
│       ├── screenshot.py    # 截图处理
│       └── ui_operator.py   # UI 操作
└── data/
    └── learning_check/
        ├── input/       # 账号文件目录
        └── output/      # 运行结果输出
```

## 注意事项

- 需要启动安卓模拟器并确保 ADB 连接正常
- OCR 功能需要较大内存（建议 8GB+）
- 账号密码文件包含敏感信息，注意保管
