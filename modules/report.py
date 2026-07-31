import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from account_source import write_retry_usernames


def _safe_account_result(result: Dict) -> Dict:
    return {
        "username": result.get("username", ""),
        "store_name": result.get("store_name", ""),
        "user_name": result.get("user_name", ""),
        "account_type": result.get("account_type", ""),
        "success": result.get("success", False),
        "status": result.get("status", ""),
        "screenshot": result.get("screenshot"),
        "message": result.get("message", ""),
    }


def save_json(path: Path, data: Dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_reports(run_dir: Path, automation_results: List[Dict], ocr_results: Dict, source_info: Dict, start_time: datetime, end_time: datetime) -> Dict:
    run_dir = Path(run_dir)
    safe_results = [_safe_account_result(result) for result in automation_results]
    failed = [result for result in safe_results if not result.get("success")]
    login_failed = [result for result in failed if result.get("status") == "login_failed"]
    password_expire = [result for result in failed if result.get("status") == "password_expire"]
    other_failed = [result for result in failed if result.get("status") not in {"login_failed", "password_expire"}]
    uncompleted = [detail for detail in ocr_results.get("details", []) if detail.get("overall") != "已完成"]

    report = {
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "duration_minutes": round((end_time - start_time).total_seconds() / 60, 2),
        "source": source_info,
        "summary": {
            "total_accounts": len(safe_results),
            "screenshot_success": len([result for result in safe_results if result.get("success")]),
            "failed_count": len(failed),
            "login_failed_count": len(login_failed),
            "password_expire_count": len(password_expire),
            "other_failed_count": len(other_failed),
            "learning_uncompleted_count": len(uncompleted),
            "learning_completed_count": ocr_results.get("completed", 0),
        },
        "failed_accounts": failed,
        "login_failed_accounts": login_failed,
        "password_expire_accounts": password_expire,
        "other_failed_accounts": other_failed,
        "uncompleted_learning": uncompleted,
    }

    save_json(run_dir / "ocr_results.json", ocr_results)
    save_json(run_dir / "execution_report.json", report)
    save_json(run_dir / "result.json", {"accounts": safe_results, "summary": report["summary"]})

    failed_lines = []
    for item in failed:
        failed_lines.append(f"{item.get('store_name')} {item.get('user_name')} {item.get('username')} - {item.get('message')}")
    (run_dir / "failed_accounts.txt").write_text("\n".join(failed_lines), encoding="utf-8")

    uncompleted_usernames = [item.get("username", "") for item in uncompleted if item.get("username")]
    write_retry_usernames(run_dir / "uncompleted_accounts.csv", uncompleted_usernames)

    return report


def write_weekday_retry_list(data_dir: Path, weekday: int, report: Dict):
    """写入第二天需要重试的账号名单（包括未完成和失败的）"""
    retry_dir = Path(data_dir) / "learning_check" / "retry_sources"

    # 收集需要重试的用户名
    retry_usernames = set()

    # 1. OCR 未完成的
    for item in report.get("uncompleted_learning", []):
        if item.get("username"):
            retry_usernames.add(item["username"])

    # 2. 登录失败的（密码错误、密码到期等）
    for item in report.get("login_failed_accounts", []):
        if item.get("username"):
            retry_usernames.add(item["username"])

    # 3. 密码到期的
    for item in report.get("password_expire_accounts", []):
        if item.get("username"):
            retry_usernames.add(item["username"])

    # 4. 其他失败的
    for item in report.get("other_failed_accounts", []):
        if item.get("username"):
            retry_usernames.add(item["username"])

    write_retry_usernames(retry_dir / f"weekday_{weekday}_uncompleted.csv", list(retry_usernames))


def pack_artifacts(run_dir: Path, ocr_results: Dict) -> Path:
    run_dir = Path(run_dir)
    zip_path = run_dir / f"screenshots_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    uncompleted = {item.get("screenshot") for item in ocr_results.get("details", []) if item.get("overall") != "已完成"}

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_name in ["execution_report.json", "ocr_results.json", "failed_accounts.txt", "screenshot_metadata.json"]:
            file_path = run_dir / file_name
            if file_path.exists():
                zf.write(file_path, file_path.name)
        screenshots_dir = run_dir / "screenshots"
        if screenshots_dir.exists():
            for image_path in screenshots_dir.glob("*.png"):
                arcname = f"screenshots/{image_path.name}"
                if str(image_path) in uncompleted:
                    arcname = f"screenshots/未完成_{image_path.name}"
                zf.write(image_path, arcname)
    return zip_path


def format_notify_content(report: Dict) -> str:
    summary = report.get("summary", {})
    source = report.get("source", {})
    lines = [
        f"**数据源：**{source.get('source_type', '')} | 周{source.get('weekday', '')}",
        f"**账号：**{summary.get('total_accounts', 0)} | **截图成功：**{summary.get('screenshot_success', 0)}",
        f"**未完成：**{summary.get('learning_uncompleted_count', 0)} | **失败：**{summary.get('failed_count', 0)}",
    ]

    uncompleted = report.get("uncompleted_learning", [])
    if uncompleted:
        lines.extend(["", f"**未完成名单（{len(uncompleted)}）**"])
        for index, item in enumerate(uncompleted, 1):
            chendu = item.get("chendu", "")
            dalianbing = item.get("dalianbing", "")
            parts = []
            if chendu and not chendu.startswith("已完成"):
                parts.append("晨读")
            if dalianbing and not dalianbing.startswith("已完成"):
                parts.append("大练兵")
            detail = "/".join(parts) if parts else "未完成"
            lines.append(f"> {index}. {item.get('store_name', '')} - {item.get('user_name', '')}（{detail}）")

    password_expire = report.get("password_expire_accounts", [])
    login_failed = report.get("login_failed_accounts", [])
    other_failed = report.get("other_failed_accounts", [])

    if password_expire:
        lines.extend(["", f"**密码到期（{len(password_expire)}）**"])
        for index, item in enumerate(password_expire, 1):
            lines.append(f"> {index}. {item.get('store_name', '')} - {item.get('user_name', '')}")

    if login_failed:
        lines.extend(["", f"**账号或密码错误（{len(login_failed)}）**"])
        for index, item in enumerate(login_failed, 1):
            lines.append(f"> {index}. {item.get('store_name', '')} - {item.get('user_name', '')}")

    if other_failed:
        lines.extend(["", f"**其他失败（{len(other_failed)}）**"])
        for index, item in enumerate(other_failed, 1):
            lines.append(f"> {index}. {item.get('store_name', '')} - {item.get('user_name', '')}: {item.get('message', '')}")

    lines.append(f"\n_{datetime.now().strftime('%m-%d %H:%M')}_")
    return "\n".join(lines)
