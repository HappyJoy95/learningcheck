import subprocess
import time
from datetime import datetime
from pathlib import Path


class ScreenshotManager:
    def __init__(self, adb_manager, screenshot_dir: Path, log_callback=None):
        self.adb = adb_manager
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.log_callback = log_callback

    def _log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def _get_screen_orientation(self) -> str:
        """获取当前屏幕方向"""
        try:
            output = self.adb.run_command("shell dumpsys input | grep SurfaceOrientation")
            if 'orientation: 1' in output or 'orientation: 3' in output:
                return "landscape"
        except Exception:
            pass
        return "portrait"

    def take_screenshot(self, filename=None):
        if filename is None:
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = self.screenshot_dir / filename
        return self._take_png_screenshot(filepath)

    def _take_png_screenshot(self, filepath: Path):
        # 截图前锁定竖屏方向
        try:
            self.adb.run_command("shell settings put system accelerometer_rotation 0")
            self.adb.run_command("shell settings put system user_rotation 0")
            time.sleep(0.5)
        except Exception:
            pass

        device_path = f"/sdcard/screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        try:
            result = subprocess.run(
                [self.adb.adb_path, "-s", self.adb.port, "shell", "screencap", "-p", device_path],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                self._log(f"设备截图失败: {result.stderr.strip()}")
                return None

            time.sleep(1)
            pull_result = subprocess.run(
                [self.adb.adb_path, "-s", self.adb.port, "pull", device_path, str(filepath)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            subprocess.run(
                [self.adb.adb_path, "-s", self.adb.port, "shell", "rm", device_path],
                capture_output=True,
                timeout=5,
            )

            if pull_result.returncode != 0:
                self._log(f"拉取截图失败: {pull_result.stderr.strip()}")
                return None
            if not filepath.exists() or filepath.stat().st_size == 0:
                self._log("截图文件未生成或为空")
                return None

            # 检查截图方向，如果横屏则旋转为竖屏
            self._rotate_if_landscape(filepath)
            return str(filepath)
        except subprocess.TimeoutExpired:
            self._log("截图超时")
            return None

    def _rotate_if_landscape(self, filepath: Path):
        """如果截图是横屏，旋转为竖屏"""
        try:
            from PIL import Image
            img = Image.open(filepath)
            width, height = img.size
            if width > height:
                self._log(f"截图横屏({width}x{height})，旋转为竖屏")
                img = img.rotate(90, expand=True)
                img.save(filepath)
        except ImportError:
            self._log("PIL 未安装，跳过截图旋转")
        except Exception as e:
            self._log(f"截图旋转失败: {e}")

    def take_screenshot_with_retry(self, username, step_name, max_retries=3):
        for attempt in range(max_retries):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_username = username.replace("@", "_").replace(".", "_")
            result = self.take_screenshot(f"{safe_username}_{step_name}_{timestamp}.png")
            if result:
                return result
            if attempt < max_retries - 1:
                time.sleep(3 + attempt)
        return None
