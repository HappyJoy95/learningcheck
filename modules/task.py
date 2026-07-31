import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from pathlib import Path

from base import BaseTask, TaskResult, TaskStatus

sys.path.insert(0, str(Path(__file__).parent))

from account_source import resolve_accounts, update_account_flags
from ocr import LearningOCR, get_current_week
from report import format_notify_content, generate_reports, pack_artifacts
from upload import upload_reports
from workflow import AutomationWorkflow

DATA_DIR = Path(__file__).parent.parent / "data"


class LearningCheckTask(BaseTask):
    task_id = "learning_check"
    task_name = "学习检查自动化"

    def _log_info(self, message: str):
        self.log("INFO", message)

    def run(self) -> TaskResult:
        self.status = TaskStatus.RUNNING
        start_time = datetime.now()
        run_id = start_time.strftime("%Y%m%d_%H%M%S")
        run_dir = DATA_DIR / "learning_check" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        self.log("INFO", f"开始执行学习检查自动化: {run_id}")

        try:
            self.update_progress(5, "解析账号数据源...")
            source = resolve_accounts(self.config, DATA_DIR, run_dir, self._log_info)
            accounts = source.accounts
            self.log("INFO", source.mail_message)
            self.log("INFO", f"周{source.weekday} 策略: {source.source_type}，账号数: {len(accounts)}")

            source_info = {
                "source_path": str(source.source_path),
                "source_type": source.source_type,
                "weekday": source.weekday,
                "mail_refreshed": source.mail_refreshed,
                "mail_message": source.mail_message,
            }

            if not accounts:
                end_time = datetime.now()
                report = {
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "source": source_info,
                    "summary": {
                        "total_accounts": 0,
                        "screenshot_success": 0,
                        "failed_count": 0,
                        "learning_uncompleted_count": 0,
                    },
                    "failed_accounts": [],
                    "uncompleted_learning": [],
                }
                (run_dir / "execution_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                return TaskResult(
                    success=True,
                    message="无未完成账号需要复查",
                    data={"total": 0, "store_names": []},
                    start_time=start_time,
                    end_time=end_time,
                    notify_title="学习检查自动化报告",
                    notify_content="无未完成账号需要复查",
                    attachment_path=str(run_dir / "execution_report.json"),
                )

            if self.dry_run:
                end_time = datetime.now()
                content = "\n".join([
                    f"**测试模式：**不会操作模拟器",
                    f"**周几：**{source.weekday}",
                    f"**策略：**{source.source_type}",
                    f"**账号数：**{len(accounts)}",
                    f"**邮件刷新：**{'是' if source.mail_refreshed else '否'}",
                ])
                return TaskResult(
                    success=True,
                    message=f"测试通过，账号数: {len(accounts)}",
                    data={"total": len(accounts), "source_type": source.source_type},
                    start_time=start_time,
                    end_time=end_time,
                    notify_title="学习检查自动化报告",
                    notify_content=content,
                )

            self.update_progress(15, "执行模拟器截图...")
            adb_port = self.config.get("adb_port", "127.0.0.1:16384")
            ocr_enabled = bool(source.strategy.get("ocr_enabled", self.config.get("automation", {}).get("ocr_enabled", True)))
            ocr_workers = int(source.strategy.get("ocr_workers") or self.config.get("automation", {}).get("ocr_workers", 2))
            ocr_week_num = get_current_week()
            ocr_futures = []
            ocr_executor = ThreadPoolExecutor(max_workers=max(1, ocr_workers)) if ocr_enabled else None
            pending_metadata = []

            def submit_ocr(metadata_item):
                pending_metadata.append(metadata_item)
                self._log_info(f"记录截图: {metadata_item.get('store_name', '')} {metadata_item.get('user_name', '')}")

            workflow = AutomationWorkflow(
                adb_port=adb_port,
                run_dir=run_dir,
                config=self.config,
                log_callback=self._log_info,
                stop_checker=self.check_stopped,
                screenshot_callback=submit_ocr if ocr_enabled else None,
            )
            batch_size = int(source.strategy.get("batch_size") or self.config.get("automation", {}).get("batch_size", 30))
            automation_results = workflow.run_accounts(accounts, batch_size=batch_size)

            if ocr_enabled and pending_metadata:
                self._log_info(f"开始提交 OCR: {len(pending_metadata)} 张图片")
                for metadata_item in pending_metadata:
                    def run_one(item=metadata_item):
                        return LearningOCR(log_callback=self._log_info, workers=1).analyze_item(item, ocr_week_num)
                    ocr_futures.append(ocr_executor.submit(run_one))

            self.update_progress(75, "执行 OCR 分析...")
            metadata_path = run_dir / "screenshot_metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else []
            if ocr_enabled:
                self._log_info(f"等待 OCR 完成: {len(ocr_futures)} 张图片")
                ocr_timeout = int(self.config.get("automation", {}).get("ocr_timeout_seconds", 120))
                ocr_details = []
                try:
                    for i, future in enumerate(ocr_futures):
                        try:
                            detail = future.result(timeout=ocr_timeout)
                            ocr_details.append(detail)
                        except FuturesTimeoutError:
                            self._log_info(f"OCR 第 {i+1}/{len(ocr_futures)} 张超时 ({ocr_timeout}s)，跳过")
                            future.cancel()
                            ocr_details.append(None)
                        except Exception as e:
                            self._log_info(f"OCR 第 {i+1}/{len(ocr_futures)} 张异常: {e}")
                            ocr_details.append(None)
                finally:
                    if ocr_executor:
                        ocr_executor.shutdown(wait=False)
                ocr_results = LearningOCR.results_from_details([d for d in ocr_details if d], ocr_week_num)
            else:
                ocr_results = {
                    "timestamp": datetime.now().isoformat(),
                    "current_week": None,
                    "total": len(metadata),
                    "completed": 0,
                    "uncompleted": len(metadata),
                    "details": [
                        {
                            **item,
                            "chendu": "未检查",
                            "dalianbing": "未检查",
                            "overall": "未完成",
                            "timestamp": datetime.now().isoformat(),
                        }
                        for item in metadata
                    ],
                }

            self.update_progress(90, "生成报告...")
            end_time = datetime.now()
            report = generate_reports(run_dir, automation_results, ocr_results, source_info, start_time, end_time)
            attachment = pack_artifacts(run_dir, ocr_results)
            notify_content = format_notify_content(report)

            # 更新 accounts.csv 中的 flag：已完成→0
            input_dir = DATA_DIR / self.config.get("account_source", {}).get("input_dir", "learning_check/input")
            accounts_csv = input_dir / self.config.get("account_source", {}).get("full_source", "accounts.csv")
            uncompleted_usernames = set()
            for item in report.get("uncompleted_learning", []):
                if item.get("username"):
                    uncompleted_usernames.add(item["username"])
            for item in report.get("failed_accounts", []):
                if item.get("username"):
                    uncompleted_usernames.add(item["username"])
            all_usernames = {account.get("username", "") for account in accounts}
            completed_usernames = all_usernames - uncompleted_usernames
            update_account_flags(accounts_csv, completed_usernames)
            self._log_info(f"已更新 flag: 完成 {len(completed_usernames)} 个→0，未完成 {len(uncompleted_usernames)} 个保留")

            # 上传报告到远程服务器
            self.update_progress(92, "上传报告到服务器...")
            upload_success = upload_reports(run_dir, self.config, self._log_info)

            # 打包完成后清理未压缩的截图
            screenshots_dir = run_dir / "screenshots"
            if screenshots_dir.exists():
                shutil.rmtree(screenshots_dir)

            # 每周首次执行清理历史 ZIP
            self._cleanup_old_archives()

            # 清理含密码的临时文件
            (run_dir / "accounts_used.csv").unlink(missing_ok=True)

            self.status = TaskStatus.COMPLETED
            self.update_progress(100, "完成")
            return TaskResult(
                success=True,
                message=f"学习检查完成，账号 {len(accounts)} 个，未完成 {report['summary']['learning_uncompleted_count']} 个",
                data={
                    "total": len(accounts),
                    "uncompleted": report["summary"]["learning_uncompleted_count"],
                    "store_names": [item.get("store_name", "") for item in report.get("uncompleted_learning", [])],
                    "run_dir": str(run_dir),
                },
                start_time=start_time,
                end_time=end_time,
                notify_title="学习检查自动化报告",
                notify_content=notify_content,
                attachment_path=str(attachment),
            )
        except Exception as e:
            self.status = TaskStatus.ERROR
            self.log("ERROR", f"学习检查失败: {e}")
            import traceback
            self.log("ERROR", traceback.format_exc())
            return TaskResult(
                success=False,
                message=f"学习检查失败: {e}",
                error=str(e),
                start_time=start_time,
                end_time=datetime.now(),
                notify_title="学习检查自动化失败",
                notify_content=str(e),
            )

    def _cleanup_old_archives(self):
        """每周首次执行时清理历史 ZIP 压缩包"""
        schedule = self.config.get("schedule", "")
        if not schedule:
            return

        try:
            parts = schedule.strip().split()
            dow_field = parts[4]  # day-of-week: 0=Sun,1=Mon,...,6=Sat
            # cron 0=Sun,1=Mon...6=Sat → Python 0=Mon...6=Sun
            cron_to_python = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}
            dow_days = set()
            for part in dow_field.split(","):
                part = part.strip()
                if part == "*":
                    return  # 每天都跑，不清理
                dow_days.add(cron_to_python[int(part)])

            # 取最小值作为"本周清理日"（周一=0 最小）
            cleanup_day = min(dow_days)
            if datetime.now().weekday() != cleanup_day:
                return

            # 遍历 run 目录，删除 ZIP
            learning_dir = DATA_DIR / "learning_check"
            if not learning_dir.exists():
                return

            deleted = 0
            for run_dir in learning_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                for zip_file in run_dir.glob("screenshots_*.zip"):
                    zip_file.unlink()
                    deleted += 1

            if deleted:
                self.log("INFO", f"清理历史压缩包 {deleted} 个")
        except Exception:
            pass