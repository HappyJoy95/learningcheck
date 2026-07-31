import csv
import imaplib
import os
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

REQUIRED_COLUMNS = ["username", "password", "account_type", "user_name", "store_name"]
DEFAULT_COLUMNS = ["username", "password", "account_type", "user_name", "execute_flag", "store_name", "remark"]


@dataclass
class AccountSourceResult:
    accounts: List[Dict[str, str]]
    source_path: Path
    source_type: str
    weekday: int
    strategy: Dict
    mail_refreshed: bool
    mail_message: str
    retry_usernames: Optional[Set[str]] = None


def _decode_str(value: Optional[str]) -> str:
    if value is None:
        return ""
    parts = decode_header(value)
    result = []
    for data, charset in parts:
        if isinstance(data, bytes):
            result.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(data)
    return "".join(result)


def _read_csv_text(path: Path) -> Tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace"), "utf-8-replace"


def load_accounts(path: Path, active_only: bool = True) -> List[Dict[str, str]]:
    text, _ = _read_csv_text(path)
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValueError(f"账号 CSV 为空或缺少表头: {path}")

    missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
    if missing:
        raise ValueError(f"账号 CSV 缺少必填列: {', '.join(missing)}")

    accounts = []
    for row in reader:
        normalized = {key: (value or "").strip() for key, value in row.items()}
        flag = normalized.get("execute_flag", "1")
        if active_only and flag != "1":
            continue
        if any(not normalized.get(column) for column in REQUIRED_COLUMNS):
            continue
        accounts.append(normalized)
    return accounts


def write_accounts(path: Path, accounts: List[Dict[str, str]], include_password: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = DEFAULT_COLUMNS if include_password else ["username", "account_type", "user_name", "store_name", "remark"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for account in accounts:
            writer.writerow(account)


def reset_flags_to_one(path: Path, data_dir: Path) -> int:
    """每周首次执行时，将所有 flag 重置为 1，返回重置数量"""
    # 检查本周是否已重置
    current_week = datetime.now().isocalendar()[1]
    week_marker_file = data_dir / "learning_check" / ".last_reset_week"
    if week_marker_file.exists():
        try:
            last_week = int(week_marker_file.read_text(encoding="utf-8").strip())
            if last_week == current_week:
                return 0  # 本周已重置
        except Exception:
            pass

    # 执行重置
    if not path.exists():
        return 0
    accounts = load_accounts(path, active_only=False)
    reset_count = 0
    for account in accounts:
        if account.get("execute_flag", "1") != "1":
            account["execute_flag"] = "1"
            reset_count += 1
    if reset_count > 0:
        write_accounts(path, accounts, include_password=True)

    # 记录本周已重置
    week_marker_file.parent.mkdir(parents=True, exist_ok=True)
    week_marker_file.write_text(str(current_week), encoding="utf-8")
    return reset_count


def update_account_flags(csv_path: Path, completed_usernames: Set[str]):
    """执行完成后更新 flag：已完成→0"""
    if not csv_path.exists():
        return
    accounts = load_accounts(csv_path, active_only=False)
    for account in accounts:
        if account.get("username", "") in completed_usernames:
            account["execute_flag"] = "0"
    write_accounts(csv_path, accounts, include_password=True)


def write_retry_usernames(path: Path, usernames: List[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["username"])
        writer.writeheader()
        for username in usernames:
            writer.writerow({"username": username})


def read_retry_usernames(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    text, _ = _read_csv_text(path)
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames or "username" not in reader.fieldnames:
        raise ValueError(f"未完成账号名单缺少 username 列: {path}")
    return {row.get("username", "").strip() for row in reader if row.get("username", "").strip()}


def _latest_attachment(mail_config: Dict, log: Callable[[str], None]) -> Optional[bytes]:
    # 优先读取专用环境变量，回退到通用 SMTP 配置
    email_env_name = mail_config.get("email_env", "")
    auth_code_env_name = mail_config.get("auth_code_env", "")
    email_addr = os.environ.get(email_env_name, "").strip() if email_env_name else ""
    auth_code = os.environ.get(auth_code_env_name, "").strip() if auth_code_env_name else ""
    if not email_addr or not auth_code:
        email_addr = os.environ.get("SMTP_USER", "").strip()
        auth_code = os.environ.get("SMTP_PASSWORD", "").strip()
    # 回退到通用配置文件
    if not email_addr or not auth_code:
        try:
            import yaml
            # modules/ -> learningcheck/config/general.yaml
            config_file = Path(__file__).parent.parent / "config" / "general.yaml"
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                email_addr = email_addr or config.get("smtp_user", "")
                auth_code = auth_code or config.get("smtp_password", "")
        except Exception:
            pass
    if not email_addr or not auth_code:
        log("邮件账号环境变量未配置，跳过邮件刷新")
        return None

    server = mail_config.get("server", "imap.qq.com")
    port = int(mail_config.get("port", 993))
    folder = mail_config.get("folder", "INBOX")
    attachment_name = mail_config.get("attachment_name", "accounts.csv")
    max_scan = int(mail_config.get("max_scan", 50))

    conn = imaplib.IMAP4_SSL(server, port)
    try:
        conn.login(email_addr, auth_code)
        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"无法打开邮箱文件夹: {folder}")

        status, msg_ids = conn.search(None, "ALL")
        if status != "OK" or not msg_ids[0]:
            log("邮箱中未找到邮件")
            return None

        ids = msg_ids[0].split()
        ids.reverse()
        for mid in ids[:max_scan]:
            status, msg_data = conn.fetch(mid, "(RFC822)")
            if status != "OK" or not msg_data:
                continue
            msg = message_from_bytes(msg_data[0][1])
            subject = _decode_str(msg.get("Subject", ""))
            date_value = msg.get("Date", "")
            try:
                date_display = parsedate_to_datetime(date_value).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date_display = date_value

            for part in msg.walk():
                filename = part.get_filename()
                if not filename:
                    continue
                filename = _decode_str(filename)
                if filename.lower() != attachment_name.lower():
                    continue
                payload = part.get_payload(decode=True)
                if payload:
                    log(f"找到账号附件: {filename}，邮件时间: {date_display}，主题: {subject}")
                    return payload
        log(f"最近 {max_scan} 封邮件未找到附件: {attachment_name}")
        return None
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def refresh_full_source(config: Dict, input_dir: Path, log: Callable[[str], None]) -> Tuple[bool, str, Path]:
    source_config = config.get("account_source", {})
    full_source = source_config.get("full_source", "accounts.csv")
    full_path = input_dir / full_source
    mail_config = source_config.get("mail", {})

    if source_config.get("mode") not in {"mail_then_local", "mail"} or not mail_config.get("enabled", False):
        return False, "账号源配置为仅本地文件，未执行邮件刷新", full_path

    try:
        payload = _latest_attachment(mail_config, log)
        if not payload:
            return False, "未获取到新的邮件附件", full_path

        temp_path = input_dir / f".{full_source}.download"
        input_dir.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(payload)
        accounts = load_accounts(temp_path, active_only=False)
        if not accounts:
            temp_path.unlink(missing_ok=True)
            raise ValueError("邮件附件中没有有效账号记录")

        full_path.write_bytes(temp_path.read_bytes())
        temp_path.unlink(missing_ok=True)
        return True, f"邮件刷新成功，更新全量账号源: {full_source}", full_path
    except Exception as e:
        log(f"邮件刷新失败: {e}")
        return False, f"邮件刷新失败: {e}", full_path


def resolve_accounts(config: Dict, data_dir: Path, run_dir: Path, log: Callable[[str], None]) -> AccountSourceResult:
    source_config = config.get("account_source", {})
    input_dir = data_dir / source_config.get("input_dir", "learning_check/input")

    mail_refreshed, mail_message, full_path = refresh_full_source(config, input_dir, log)
    if not full_path.exists():
        raise FileNotFoundError(f"全量账号文件不存在: {full_path}")

    weekday = datetime.now().isoweekday()
    strategies = source_config.get("weekday_strategies", {})
    strategy = strategies.get(str(weekday), {"source_type": "full"})
    source_type = strategy.get("source_type", "full")

    # 每周首次执行重置所有 flag 为 1
    reset_count = reset_flags_to_one(full_path, data_dir)
    if reset_count > 0:
        log(f"每周重置: {reset_count} 个账号 flag 已重置为 1")

    full_accounts = load_accounts(full_path, active_only=True)
    if not full_accounts:
        raise ValueError(f"全量账号文件没有可执行账号: {full_path}")

    # 执行 flag=1 的账号，flag=0 跳过
    retry_usernames = None
    selected_accounts = full_accounts

    run_accounts_path = run_dir / "accounts_used.csv"
    write_accounts(run_accounts_path, selected_accounts, include_password=True)

    return AccountSourceResult(
        accounts=selected_accounts,
        source_path=full_path,
        source_type=source_type,
        weekday=weekday,
        strategy=strategy,
        mail_refreshed=mail_refreshed,
        mail_message=mail_message,
        retry_usernames=retry_usernames,
    )
