"""
任务基类 - 简化版用于独立运行
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum
import threading


class TaskStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"
    COMPLETED = "completed"


@dataclass
class TaskResult:
    """任务执行结果"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    notify_title: Optional[str] = None
    notify_content: Optional[str] = None
    notify_content_type: Optional[str] = None
    attachment_path: Optional[str] = None


class BaseTask(ABC):
    """任务基类"""

    task_id: str = "base"
    task_name: str = "基础任务"

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.status = TaskStatus.IDLE
        self.progress = 0
        self.message = ""
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._status_callback = None
        self._log_callback = None
        self._run_mode = "normal"

    @property
    def dry_run(self) -> bool:
        return self._run_mode == "test"

    @abstractmethod
    def run(self) -> TaskResult:
        pass

    def stop(self):
        self._stop_event.set()
        self.status = TaskStatus.STOPPED

    def check_stopped(self) -> bool:
        return self._stop_event.is_set()

    def update_progress(self, progress: int, message: str = ""):
        self.progress = min(100, max(0, progress))
        self.message = message
        if self._status_callback:
            self._status_callback({
                "task_id": self.task_id,
                "status": self.status.value,
                "progress": self.progress,
                "message": self.message
            })

    def set_log_callback(self, callback):
        self._log_callback = callback

    def log(self, level: str, message: str):
        if self._log_callback:
            self._log_callback(level, message)
        else:
            print(f"[{level}] {message}")