#!/usr/bin/env python3
"""
学习检查自动化 - 独立运行入口
"""
import json
import sys
import os
import smtplib
import yaml
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime

# 添加模块路径
sys.path.insert(0, str(Path(__file__).parent / "modules"))

from task import LearningCheckTask, DATA_DIR


def load_config(config_path: Path) -> dict:
    """加载配置文件"""
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_general_config() -> dict:
    """加载通用配置"""
    config_path = Path(__file__).parent / "config" / "general.yaml"
    if not config_path.exists():
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def send_email(subject: str, content: str, attachment_path: str = None) -> bool:
    """发送邮件通知"""
    general = load_general_config()
    smtp_server = general.get("smtp_server", "smtp.qq.com")
    smtp_port = general.get("smtp_port", 587)
    smtp_user = general.get("smtp_user", "")
    smtp_password = general.get("smtp_password", "")

    if not smtp_user or not smtp_password:
        print("邮件配置不完整，跳过发送")
        return False

    # 收件人从 config.json 读取
    config_path = Path(__file__).parent / "config" / "config.json"
    config = load_config(config_path)
    recipients = config.get("notify_email_target", "")
    if not recipients:
        print("未配置收件人，跳过发送")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = recipients
        msg["Subject"] = subject

        # 邮件正文（HTML格式）
        html_content = content.replace("\n", "<br>")
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        # 添加附件（50MB以内）
        if attachment_path:
            attach_file = Path(attachment_path)
            if attach_file.exists() and attach_file.stat().st_size <= 50 * 1024 * 1024:
                from email.mime.base import MIMEBase
                from email import encoders
                with open(attach_file, "rb") as f:
                    part = MIMEBase("application", "zip")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={attach_file.name}")
                msg.attach(part)
            elif attach_file.exists():
                print(f"附件过大({attach_file.stat().st_size / 1024 / 1024:.1f}MB)，跳过附件")

        # 发送
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        print(f"邮件已发送至 {recipients}")
        return True
    except Exception as e:
        print(f"邮件发送失败: {e}")
        return False


def main():
    """主函数"""
    print("=" * 50)
    print("学习检查自动化 - 独立运行模式")
    print("=" * 50)

    # 加载配置
    config_path = Path(__file__).parent / "config" / "config.json"
    config = load_config(config_path)

    if not config:
        print("错误: 无法加载配置文件")
        return 1

    # 创建任务实例
    task = LearningCheckTask(config=config)

    # 设置日志回调
    def log_callback(level, message, task_id=None):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

    task.set_log_callback(log_callback)

    # 执行任务
    print("\n开始执行学习检查任务...")
    result = task.run()

    # 输出结果
    print("\n" + "=" * 50)
    print(f"任务完成: {result.message}")
    print(f"成功: {result.success}")

    if result.data:
        print(f"总账号数: {result.data.get('total', 0)}")
        print(f"未完成数: {result.data.get('uncompleted', 0)}")

    if result.attachment_path:
        print(f"报告路径: {result.attachment_path}")

    # 发送邮件通知
    if config.get("notify_enabled") and "email" in config.get("notify_type", []):
        print("\n发送邮件通知...")
        send_email(
            subject=result.notify_title or "学习检查自动化报告",
            content=result.notify_content or result.message,
            attachment_path=result.attachment_path,
        )

    print("=" * 50)

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())