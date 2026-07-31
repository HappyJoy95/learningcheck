import time
from pathlib import Path


class UIOperator:
    ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"

    def __init__(self, adb_manager, log_callback=None):
        self.adb = adb_manager
        self.log_callback = log_callback

    def _log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def tap(self, x, y, wait_time=1):
        ok = self.adb.run_command(f"shell input tap {x} {y}") is not None
        if not ok:
            self._log(f"点击命令未确认: ({x}, {y})")
        if wait_time > 0:
            time.sleep(wait_time)
        return ok

    def input_text(self, x, y, text, wait_time=1, force_clipboard=False):
        self.tap(x, y, 0.5)
        self.adb.run_command("shell input keyevent KEYCODE_MOVE_END")
        for _ in range(50):
            self.adb.run_command("shell input keyevent KEYCODE_DEL")

        has_non_ascii = any(ord(char) > 127 for char in text)
        special_chars = set(" ,'\"()&|;<>\n\t#@$.!")
        has_special = bool(set(text) & special_chars)

        if has_non_ascii or has_special or force_clipboard:
            if self.ensure_adb_keyboard():
                self._input_via_adb_keyboard(text)
            else:
                self._log("ADB 输入法不可用，回退到 adb shell input text")
                self.adb.run_adb(["-s", self.adb.port, "shell", "input", "text", text])
        else:
            self.adb.run_adb(["-s", self.adb.port, "shell", "input", "text", text])

        if wait_time > 0:
            time.sleep(wait_time)

    def ensure_adb_keyboard(self) -> bool:
        current = self.adb.run_command("shell settings get secure default_input_method") or ""
        if self.ADB_KEYBOARD_IME in current:
            return True

        enabled = self.adb.run_command("shell ime list -s") or ""
        if self.ADB_KEYBOARD_IME not in enabled:
            apk_path = Path(__file__).with_name("ADBKeyboard.apk")
            if not apk_path.exists():
                self._log(f"未找到 ADBKeyboard.apk: {apk_path}")
                return False

            self._log("安装 ADBKeyboard...")
            result = self.adb.run_adb(["-s", self.adb.port, "install", "-r", str(apk_path)], timeout=60)
            output = ((result.stdout or "") + (result.stderr or "")) if result else ""
            if result is None or result.returncode != 0:
                self._log(f"ADBKeyboard 安装失败: {output.strip()}")
                return False

        self._log("切换到 ADB 输入法...")
        self.adb.run_adb(["-s", self.adb.port, "shell", "ime", "enable", self.ADB_KEYBOARD_IME], timeout=10)
        result = self.adb.run_adb(["-s", self.adb.port, "shell", "ime", "set", self.ADB_KEYBOARD_IME], timeout=10)
        output = ((result.stdout or "") + (result.stderr or "")) if result else ""
        if result is None or result.returncode != 0:
            self._log(f"切换 ADB 输入法失败: {output.strip()}")
            return False

        time.sleep(0.5)
        current = self.adb.run_command("shell settings get secure default_input_method") or ""
        if self.ADB_KEYBOARD_IME in current:
            self._log("ADB 输入法已启用")
            return True

        self._log(f"ADB 输入法未生效，当前输入法: {current}")
        return False

    def _input_via_adb_keyboard(self, text: str):
        self.adb.run_adb(["-s", self.adb.port, "shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", text])
        time.sleep(0.2)

    def swipe(self, x1, y1, x2, y2, duration=500, wait_time=1):
        self.adb.run_command(f"shell input swipe {x1} {y1} {x2} {y2} {duration}")
        if wait_time > 0:
            time.sleep(wait_time)

    def back(self, wait_time=1):
        ok = self.adb.run_command("shell input keyevent KEYCODE_BACK") is not None
        if not ok:
            self._log("返回键命令未确认")
        if wait_time > 0:
            time.sleep(wait_time)
        return ok

    def keyevent(self, event_code, wait_time=1):
        ok = self.adb.run_command(f"shell input keyevent {event_code}") is not None
        if not ok:
            self._log(f"按键命令未确认: {event_code}")
        if wait_time > 0:
            time.sleep(wait_time)
        return ok

    def wait(self, seconds):
        time.sleep(seconds)
