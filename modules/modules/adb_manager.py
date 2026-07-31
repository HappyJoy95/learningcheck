import subprocess
import os
import shutil
from pathlib import Path
from typing import Callable, Optional, Tuple


def resolve_adb_path(adb_path: str = "adb") -> str:
    """Resolve ADB to a Windows executable that can be launched reliably."""
    expanded = os.path.expandvars(os.path.expanduser(adb_path or "adb"))
    if expanded.lower() != "adb":
        return expanded

    candidates = [
        os.environ.get("ADB_PATH"),
        shutil.which("adb"),
        r"C:\platform-tools\adb.exe",
        r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
        r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\adb.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return expanded


class ADBManager:
    def __init__(self, port: str, adb_path: str = "adb", log_callback: Optional[Callable[[str], None]] = None):
        self.port = port
        self.adb_path = resolve_adb_path(adb_path)
        self.log_callback = log_callback
        if self.adb_path != adb_path:
            self._log(f"ADB路径: {self.adb_path}")

    def _log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def run_command(self, command: str, timeout: int = 10) -> Optional[str]:
        cmd_list = [self.adb_path, "-s", self.port] + command.split()
        try:
            proc = subprocess.Popen(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                self._log(f"ADB命令超时 ({timeout}s): {command}")
                return None
            if proc.returncode != 0:
                self._log(f"ADB命令失败 [{command}]: {stderr.decode('utf-8', errors='ignore').strip()}")
                return None
            return stdout.decode("utf-8", errors="ignore").strip()
        except FileNotFoundError:
            self._log(f"ADB未找到，请检查路径: {self.adb_path}")
            return None
        except OSError as e:
            self._log(f"ADB无法启动: {self.adb_path}，错误: {e}")
            return None

    def run_adb(self, args: list, timeout: int = 10) -> Optional[subprocess.CompletedProcess]:
        cmd_list = [self.adb_path] + args
        try:
            proc = subprocess.Popen(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                self._log(f"ADB命令超时 ({timeout}s): {' '.join(args)}")
                return None
            return subprocess.CompletedProcess(
                args=cmd_list, returncode=proc.returncode,
                stdout=stdout.decode("utf-8", errors="ignore"),
                stderr=stderr.decode("utf-8", errors="ignore"),
            )
        except FileNotFoundError:
            self._log(f"ADB未找到，请检查路径: {self.adb_path}")
            return None
        except OSError as e:
            self._log(f"ADB无法启动: {self.adb_path}，错误: {e}")
            return None

    def check_device(self) -> bool:
        result = self.run_adb(["devices"], timeout=10)
        if result and self.port in result.stdout and "device" in result.stdout:
            return True
        return False

    def connect_device(self, retries: int = 3, delay: float = 2.0) -> bool:
        import time
        for attempt in range(1, retries + 1):
            result = self.run_adb(["connect", self.port], timeout=10)
            if result:
                output = f"{result.stdout}\n{result.stderr}"
                if "connected" in output.lower() or "already connected" in output.lower():
                    self._log(f"已连接模拟器: {self.port}")
                    return True
            self._log(f"连接失败(第{attempt}次)")
            if attempt < retries:
                self._log(f"{delay}秒后重试...")
                time.sleep(delay)
        self._log(f"连接失败（已重试{retries}次）: {self.port}")
        return False

    def get_screen_size(self) -> Tuple[Optional[int], Optional[int]]:
        output = self.run_command("shell wm size")
        if output:
            import re
            match = re.search(r"(\d+)x(\d+)", output)
            if match:
                return int(match.group(1)), int(match.group(2))
        return None, None
