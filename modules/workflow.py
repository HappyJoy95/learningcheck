"""
学习检查自动化工作流 - 基于 test/screenshot_automation.py 稳定版本
使用硬编码坐标 + 元素检测混合模式
"""
import csv
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from modules.adb_manager import ADBManager, resolve_adb_path
from modules.screenshot import ScreenshotManager
from modules.ui_operator import UIOperator


ADB_EXE = resolve_adb_path("adb")


def run_adb_command(cmd_list, timeout=10):
    """可靠的 ADB 命令执行，不读管道避免 Windows 阻塞"""
    try:
        proc = subprocess.Popen(cmd_list, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.wait(timeout=timeout)
        return subprocess.CompletedProcess(args=cmd_list, returncode=proc.returncode, stdout=b"", stderr=b"")
    except subprocess.TimeoutExpired:
        logging.warning(f"ADB 超时 ({timeout}s): {' '.join(cmd_list)}")
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass
        return subprocess.CompletedProcess(args=cmd_list, returncode=-1, stdout=b"", stderr=b"timeout")
    except Exception as e:
        logging.warning(f"ADB 异常: {e}")
        return subprocess.CompletedProcess(args=cmd_list, returncode=-1, stdout=b"", stderr=b"error")


def run_adb_with_output(cmd_list, timeout=10):
    """ADB 命令执行并捕获输出（用于需要读取结果的命令）"""
    try:
        result = subprocess.run(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        return result
    except subprocess.TimeoutExpired:
        logging.warning(f"ADB 超时 ({timeout}s): {' '.join(cmd_list)}")
        return subprocess.CompletedProcess(args=cmd_list, returncode=-1, stdout=b"", stderr=b"timeout")
    except Exception as e:
        logging.warning(f"ADB 异常: {e}")
        return subprocess.CompletedProcess(args=cmd_list, returncode=-1, stdout=b"", stderr=b"error")


# ==================== 坐标配置（1440x2560） ====================
COORDS = {
    # 登录页面
    "username_input": (750, 460),
    "password_input": (750, 600),
    "agree_button": (380, 920),
    "login_button": (720, 788),
    "password_expire_cancel": (574, 1362),
    "login_failed_ok": (720, 1562),

    # 搜索
    "search_box": (521, 258),
    "search_bar": (719, 125),

    # 课程
    "first_course": (450, 500),
    "schedule_tab": (351, 540),

    # 返回
    "back_button": (99, 126),

    # 退出
    "my_tab": (1300, 2480),
    "settings": (1360, 95),
    "logout_button": (720, 1460),
    "logout_confirm": (866, 1389),
}


# ==================== 工具函数 ====================

def get_current_week_number():
    """获取当前周序号"""
    today = datetime.now()
    day_of_year = today.timetuple().tm_yday
    if day_of_year <= 4:
        return "W1"
    return f"W{(day_of_year - 5) // 7 + 2}"


def get_track_name(account_type):
    """根据账号类型返回赛道名称"""
    if "办公" in account_type or "智慧办公" in account_type:
        return "智慧办公赛道"
    elif "家居" in account_type or "智能家居" in account_type:
        return "智能家居赛道"
    return "个人消费赛道"


def find_element_bounds(xml_str, target_text):
    """查找元素坐标"""
    pattern = r'<node[^>]*text="' + re.escape(target_text) + r'"[^>]*bounds="\[([^,]+),([^,]+)\]\[([^,]+),([^,]+)\]"'
    match = re.search(pattern, xml_str)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))
    return None


def get_track_arrow_direction(xml_str, track_bounds):
    """获取赛道箭头方向：down=展开, up=折叠"""
    import base64
    x1, y1, x2, y2 = track_bounds
    for match in re.finditer(r'<node[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*/>', xml_str):
        full_node = match.group(0)
        ax1, ay1 = int(match.group(1)), int(match.group(2))
        if ax1 > 1300 and y1 - 20 <= ay1 <= y2 + 10:
            if "svg+xml;base64" in full_node:
                b64_match = re.search(r'svg\+xml;base64,([A-Za-z0-9+/=]+)', full_node)
                if b64_match:
                    try:
                        svg_str = base64.b64decode(b64_match.group(1)).decode('utf-8')
                        if "M2.815 10.471" in svg_str:
                            return "down"
                        elif "M2.815 5.529" in svg_str:
                            return "up"
                    except:
                        pass
    return None


def find_all_tracks(xml_str):
    """查找所有赛道及其展开状态"""
    tracks = {}
    for track_name in ['个人消费赛道', '智慧办公赛道', '智能家居赛道']:
        track_bounds = find_element_bounds(xml_str, track_name)
        if track_bounds:
            arrow = get_track_arrow_direction(xml_str, track_bounds)
            expanded = (arrow == "down")
            # SVG检测失败时，通过周序号位置判断展开状态
            if arrow is None:
                track_y = track_bounds[3]
                for w in [f"W{i}" for i in range(1, 53)]:
                    for match in re.finditer(r'<node[^>]*text="' + w + r'"[^>]*bounds="\[([^,]+),([^,]+)\]\[([^,]+),([^,]+)\]"', xml_str):
                        bounds = (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))
                        distance = bounds[1] - track_y
                        if 0 < distance < 150:
                            expanded = True
                            break
                    if expanded:
                        break
            tracks[track_name] = {
                'bounds': track_bounds,
                'expanded': expanded,
                'arrow': arrow
            }
    return tracks


def find_week_in_track(xml_str, week_num, track_name):
    """在赛道下方查找周序号"""
    track_bounds = find_element_bounds(xml_str, track_name)
    if not track_bounds:
        return None, None, False

    track_y = track_bounds[3]
    is_expanded = False
    for w in [f"W{i}" for i in range(1, 53)]:
        for match in re.finditer(r'<node[^>]*text="' + w + r'"[^>]*bounds="\[([^,]+),([^,]+)\]\[([^,]+),([^,]+)\]"', xml_str):
            bounds = (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))
            distance = bounds[1] - track_y
            if 0 < distance < 100:
                is_expanded = True
                break

    target_bounds = None
    pattern = r'<node[^>]*text="' + re.escape(week_num) + r'"[^>]*bounds="\[([^,]+),([^,]+)\]\[([^,]+),([^,]+)\]"'
    for match in re.finditer(pattern, xml_str):
        bounds = (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))
        if bounds[1] > track_y:
            target_bounds = bounds
            break

    return target_bounds, track_bounds, is_expanded


def get_current_activity(port):
    """通过 dumpsys 获取当前 Activity 名"""
    try:
        result = subprocess.run(
            [ADB_EXE, '-s', port, 'shell', 'dumpsys', 'window'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5
        )
        output = result.stdout.decode('utf-8', errors='ignore')
        match = re.search(r'mCurrentFocus=Window\{[^ ]+ u0 ([^}]+)\}', output)
        if match:
            return match.group(1)
    except Exception:
        pass
    return ""


def dump_ui(port, retries=2):
    """dump UI XML，带重试"""
    device_path = "/sdcard/ui_check.xml"

    for attempt in range(retries + 1):
        try:
            cmd = [ADB_EXE, '-s', port, 'shell', 'rm', '-f', device_path]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)

            cmd = [ADB_EXE, '-s', port, 'shell', 'uiautomator', 'dump', '--compressed', device_path]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            if result.returncode != 0:
                if attempt < retries:
                    time.sleep(2)
                    continue
                return ""

            cmd = [ADB_EXE, '-s', port, 'shell', 'cat', device_path]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=8)
            if result.returncode != 0 or not result.stdout:
                if attempt < retries:
                    time.sleep(2)
                    continue
                return ""

            for encoding in ['utf-8', 'utf-16-le', 'gbk', 'latin-1']:
                try:
                    return result.stdout.decode(encoding)
                except:
                    continue
            return ""
        except subprocess.TimeoutExpired:
            if attempt < retries:
                time.sleep(2)
                continue
            return ""
        except Exception:
            if attempt < retries:
                time.sleep(2)
                continue
            return ""
    return ""


def wait_for_activity(port, target_activities, timeout=30, interval=2, wait_after_found=3):
    """等待当前 Activity 变为目标之一"""
    start = time.time()
    while time.time() - start < timeout:
        current = get_current_activity(port)
        for target in target_activities:
            if target in current:
                logging.info(f"检测到 Activity: {current}")
                if wait_after_found > 0:
                    time.sleep(wait_after_found)
                return True
        elapsed = time.time() - start
        logging.info(f"wait_for_activity: {elapsed:.0f}s current={current}, 目标={target_activities}")
        time.sleep(interval)
    logging.warning(f"等待 Activity 超时({timeout}s): {target_activities}")
    return False


def wait_for_elements(port, expected_texts, timeout=30, interval=1, wait_after_found=5, fail_on_timeout=False):
    """等待页面元素，优先用 dump_ui，失败时回退到 dumpsys"""
    start = time.time()
    while time.time() - start < timeout:
        xml = dump_ui(port)
        if xml:
            for text in expected_texts:
                if text in xml:
                    logging.info(f"检测到元素: {text}")
                    if wait_after_found > 0:
                        time.sleep(wait_after_found)
                    return True
        elapsed = time.time() - start
        logging.info(f"wait_for_elements: {elapsed:.0f}s 未命中, xml长度={len(xml)}")
        time.sleep(interval)
    logging.warning(f"等待超时({timeout}s): {expected_texts}")
    return False


def check_password_expire_popup(port):
    """检测密码到期弹窗"""
    xml = dump_ui(port)
    if "密码还有" in xml and "天到期" in xml:
        return True
    if "btn_negative" in xml and "修改密码" in xml:
        return True
    if "账号密码即将过期" in xml:
        return True
    if "修改密码" in xml and "取消" in xml:
        return True
    return False


def check_login_failed_popup(port):
    """检测登录失败弹窗"""
    xml = dump_ui(port)
    if "登录失败" in xml:
        return True
    if "账号或密码错误" in xml:
        return True
    if "tv_cancel" in xml and "累计输错" in xml:
        return True
    if "com.huawei.iretail.ma:id/tv_cancel" in xml:
        return True
    return False


# 登录后弹窗关键词 → (按钮文本, 按钮坐标)
POST_LOGIN_POPUPS = {
    "用户协议": ("同意", (720, 1650)),
    "隐私政策": ("同意", (720, 1650)),
    "隐私协议": ("同意", (720, 1650)),
    "服务条款": ("同意", (720, 1650)),
    "个人信息保护": ("同意", (720, 1650)),
    "已阅读并同意": ("同意", (720, 1650)),
    "我知道了": ("我知道了", (720, 1650)),
    "暂不升级": ("暂不升级", (720, 1650)),
    "以后再说": ("以后再说", (720, 1650)),
    "取消更新": ("取消更新", (720, 1650)),
}


def check_and_dismiss_post_login_popup(port, log_callback=None):
    """检测并关闭登录后可能出现的弹窗（用户协议、隐私政策、更新提示等）

    Returns:
        True 如果检测到并处理了弹窗，False 如果没有检测到弹窗
    """
    xml = dump_ui(port)
    if not xml:
        return False

    for keyword, (btn_text, btn_coord) in POST_LOGIN_POPUPS.items():
        if keyword in xml:
            if log_callback:
                log_callback(f"检测到登录后弹窗: {keyword}，点击 [{btn_text}]")
            # 优先通过文本查找按钮坐标
            btn_bounds = find_element_bounds(xml, btn_text)
            if btn_bounds:
                x = (btn_bounds[0] + btn_bounds[2]) // 2
                y = (btn_bounds[1] + btn_bounds[3]) // 2
            else:
                x, y = btn_coord
            run_adb_command(
                [ADB_EXE, '-s', port, 'shell', 'input', 'tap', str(x), str(y)],
                timeout=10,
            )
            time.sleep(2)
            return True

    # 兜底：检测是否有未知弹窗带"同意"或"确定"按钮
    if "同意" in xml and ("协议" in xml or "政策" in xml or "条款" in xml or "保护" in xml):
        btn_bounds = find_element_bounds(xml, "同意")
        if btn_bounds:
            x = (btn_bounds[0] + btn_bounds[2]) // 2
            y = (btn_bounds[1] + btn_bounds[3]) // 2
        else:
            x, y = 720, 1650
        if log_callback:
            log_callback("检测到未知协议弹窗，点击 [同意]")
        run_adb_command(
            [ADB_EXE, '-s', port, 'shell', 'input', 'tap', str(x), str(y)],
            timeout=10,
        )
        time.sleep(2)
        return True

    return False


# ==================== 截图合成 ====================

def combine_screenshots(screenshot1, screenshot2, store_name, user_name, username):
    """合并两张截图"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    if not all([screenshot1, screenshot2]):
        return None

    for path in [screenshot1, screenshot2]:
        if not os.path.exists(path):
            return None

    img1 = Image.open(screenshot1)
    img2 = Image.open(screenshot2)
    max_height = max(img1.height, img2.height)

    def resize_height(img, target_height):
        w, h = img.size
        if h >= target_height:
            return img
        new_img = Image.new('RGB', (w, target_height), (255, 255, 255))
        new_img.paste(img, (0, (target_height - h) // 2))
        return new_img

    img1_r = resize_height(img1, max_height)
    img2_r = resize_height(img2, max_height)
    total_width = img1_r.size[0] + img2_r.size[0]

    combined = Image.new('RGBA', (total_width, max_height), (0, 0, 0, 0))
    combined.paste(img1_r.convert('RGBA'), (0, 0))
    combined.paste(img2_r.convert('RGBA'), (img1_r.size[0], 0))

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    center_x = total_width // 2
    banner_y = 24
    font_size = max_height // 28

    font = None
    for font_name in ["msyh.ttc", "simhei.ttf", "arial.ttf"]:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except:
            continue
    if font is None:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(combined)
    label = f"{current_time}  {user_name} - {store_name}  {username}"
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    bg_x1 = center_x - tw // 2 - 30
    bg_y1 = banner_y
    bg_x2 = center_x + tw // 2 + 30
    bg_y2 = banner_y + th + 40
    draw.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], fill=(0, 0, 0, 180))
    draw.text((center_x - tw // 2, banner_y + 20), label, fill=(255, 255, 255), font=font)

    result = combined.convert('RGB')
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(screenshot1).parent / f"{store_name}_{user_name}_{username}_combined_{timestamp}.png"
    result.save(output_path, 'PNG')

    for p in [screenshot1, screenshot2]:
        try:
            os.remove(p)
        except:
            pass
    return str(output_path)


# ==================== 工作流类 ====================

class AutomationWorkflow:
    def __init__(self, adb_port: str = None, run_dir: Path = None, config: Dict = None,
                 log_callback: Callable = None, stop_checker: Callable = None,
                 screenshot_callback: Callable = None):
        self.adb_port = adb_port or "127.0.0.1:16384"
        self.run_dir = Path(run_dir) if run_dir else Path("windows/data/learning_check")
        self.config = config or {}
        self.log_callback = log_callback
        self.stop_checker = stop_checker
        self.screenshot_callback = screenshot_callback
        self.screen_width = 1440
        self.screen_height = 2560

        self.adb = ADBManager(port=self.adb_port, log_callback=self._log)
        self.screenshot = ScreenshotManager(self.adb, self.run_dir / "screenshots", log_callback=self._log)
        self.ui = UIOperator(self.adb, log_callback=self._log)
        self.metadata = []

    def _log(self, msg):
        if self.log_callback:
            self.log_callback(msg)

    def _check_stopped(self):
        if self.stop_checker and self.stop_checker():
            raise InterruptedError("任务已停止")

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self._check_stopped()
            time.sleep(min(1, end - time.time()))

    def tap_and_wait(self, coord, expected_texts, timeout=10, wait_after_found=3, desc=""):
        self._log(f"点击 {desc or coord}")
        self.ui.tap(coord[0], coord[1], 1)
        self._log(f"点击完成，开始等待元素: {expected_texts}")
        start = time.time()
        while time.time() - start < timeout:
            xml = dump_ui(self.adb_port)
            if xml:
                for text in expected_texts:
                    if text in xml:
                        self._log(f"检测到: {text}")
                        if wait_after_found > 0:
                            time.sleep(wait_after_found)
                        return True
            time.sleep(2)
        self._log(f"未检测到: {expected_texts}，继续执行")
        return True

    def execute_login(self, username, password):
        """登录流程"""
        self._log("开始登录...")
        self.ui.tap(COORDS["username_input"][0], COORDS["username_input"][1], 1)
        time.sleep(1)
        self.ui.input_text(COORDS["username_input"][0], COORDS["username_input"][1], username, 1)
        time.sleep(1)
        self.ui.tap(COORDS["password_input"][0], COORDS["password_input"][1], 1)
        self.ui.input_text(COORDS["password_input"][0], COORDS["password_input"][1], password, 1, force_clipboard=True)
        time.sleep(1)

        # 检测登录按钮
        xml = dump_ui(self.adb_port)
        login_btn_match = re.search(r'resource-id="com\.huawei\.iretail\.ma:id/btn_login"[^>]*enabled="([^"]*)"', xml)
        if login_btn_match and login_btn_match.group(1) == "true":
            self._log("登录按钮已启用")
        else:
            self._log("点击用户协议")
            self.ui.tap(COORDS["agree_button"][0], COORDS["agree_button"][1], 1)
            time.sleep(1)

        self.ui.tap(COORDS["login_button"][0], COORDS["login_button"][1], 1)
        time.sleep(5)

        if check_login_failed_popup(self.adb_port):
            self._log("登录失败弹窗")
            self.ui.tap(COORDS["login_failed_ok"][0], COORDS["login_failed_ok"][1], 2)
            time.sleep(1)
            return "login_failed"

        password_expire = False
        if check_password_expire_popup(self.adb_port):
            self._log("密码到期弹窗")
            self.ui.tap(COORDS["password_expire_cancel"][0], COORDS["password_expire_cancel"][1], 2)
            time.sleep(2)
            password_expire = True

        # 检测登录后弹窗（用户协议、隐私政策等）
        for _ in range(3):
            if check_and_dismiss_post_login_popup(self.adb_port, log_callback=self._log):
                self._log("登录后弹窗已处理")
            else:
                break

        login_activity = get_current_activity(self.adb_port)
        self._log(f"点击登录后 Activity({5}s): {login_activity}")
        login_keywords = ["login", "Login", "sign", "Sign", "splash", "Splash", "auth", "welcome", "MssLogin"]

        def is_home_activity(act):
            return any(kw in act for kw in ["Main", "Home", "Course", "Dashboard"])

        if login_activity and is_home_activity(login_activity):
            self._log(f"已在主页: {login_activity}")
        else:
            logged_in = False
            for retry_round in range(2):
                for attempt in range(20):
                    # 每次循环都检测登录后弹窗
                    check_and_dismiss_post_login_popup(self.adb_port, log_callback=self._log)

                    current = get_current_activity(self.adb_port)
                    self._log(f"  [轮{retry_round+1}][{attempt+1}/20] Activity: {current}")
                    if current and is_home_activity(current):
                        self._log(f"Activity 已切换到主页: {current}")
                        logged_in = True
                        break
                    if current and current != login_activity and not any(kw in current for kw in login_keywords):
                        self._log(f"Activity 已切换: {current}")
                        logged_in = True
                        break
                    time.sleep(2)
                if logged_in:
                    break
                if retry_round == 0:
                    self._log("首次判定未登录，等待5秒后重试...")
                    time.sleep(5)
            if not logged_in:
                self._log("登录超时(80s)")
                return False

        self._log("登录成功")
        return "password_expire" if password_expire else True

    def execute_first_course(self, account_type, store_name, user_name, username):
        """晨读截图"""
        self._log("进入晨读...")
        week_num = get_current_week_number()
        track_name = get_track_name(account_type)
        self._log(f"目标: {week_num}, {track_name}")

        # 1. 搜索
        if not self.tap_and_wait(COORDS["search_box"], ["搜索历史", "大家都在搜", "Search learning", "History"], timeout=10, wait_after_found=3, desc="搜索框"):
            return False, None

        self.ui.input_text(COORDS["search_box"][0], COORDS["search_box"][1], "山东晨读2026", 1)
        time.sleep(1)
        self.ui.keyevent("KEYCODE_ENTER", 1)

        if not wait_for_elements(self.adb_port, ["综合", "智能排序", "课程", "Course(s)", "Match"], timeout=15, wait_after_found=3):
            self._log("搜索结果超时")

        # 2. 点击课程
        self.ui.tap(COORDS["first_course"][0], COORDS["first_course"][1], 1)

        # 3. 等待赛道加载
        tracks_loaded = False
        for attempt in range(7):
            xml = dump_ui(self.adb_port)
            if find_all_tracks(xml):
                self._log(f"第 {attempt+1} 次：赛道已加载")
                tracks_loaded = True
                break
            self._log(f"第 {attempt+1} 次：等待3秒...")
            time.sleep(3)

        if not tracks_loaded:
            self._log("未识别赛道，直接截图")
            screenshot1 = self.screenshot.take_screenshot(f"{store_name}_{user_name}_{username}_晨读.png")
            return bool(screenshot1), screenshot1

        # 4. 折叠所有赛道（确保干净状态）
        all_tracks = ['个人消费赛道', '智慧办公赛道', '智能家居赛道']
        for attempt in range(2):
            xml = dump_ui(self.adb_port)
            tracks_info = find_all_tracks(xml)
            self._log(f"赛道状态(第{attempt+1}次): " + ", ".join(
                f"{k}={'展开' if v['expanded'] else '折叠'}" for k, v in tracks_info.items()
            ))

            need_fold = [name for name, info in tracks_info.items() if info.get('expanded', False)]
            if not need_fold:
                self._log("所有赛道已折叠")
                break

            for track in need_fold:
                xml = dump_ui(self.adb_port)
                bounds = find_element_bounds(xml, track)
                if bounds:
                    x, y = 300, (bounds[1] + bounds[3]) // 2
                    self._log(f"折叠 {track}: ({x}, {y})")
                    run_adb_command([ADB_EXE, '-s', self.adb_port, 'shell', 'input', 'tap', str(x), str(y)], timeout=10)
                    time.sleep(2)

        # 5. 展开目标赛道
        time.sleep(1)
        xml = dump_ui(self.adb_port)
        target_bounds = find_element_bounds(xml, track_name)
        if target_bounds and target_bounds[1] > 1800:
            self._log(f"目标赛道在屏幕下方({target_bounds[1]})，先滚动")
            run_adb_command([ADB_EXE, '-s', self.adb_port, 'shell', 'input', 'swipe', '720', '600', '720', '1400', '300'], timeout=10)
            time.sleep(2)
            xml = dump_ui(self.adb_port)
            target_bounds = find_element_bounds(xml, track_name)

        if target_bounds:
            # 先检查是否已展开
            tracks_info = find_all_tracks(xml)
            if track_name in tracks_info and tracks_info[track_name].get('expanded', False):
                self._log(f"{track_name} 已展开，跳过")
            else:
                x, y = 300, (target_bounds[1] + target_bounds[3]) // 2
                self._log(f"展开 {track_name}: ({x}, {y})")
                run_adb_command([ADB_EXE, '-s', self.adb_port, 'shell', 'input', 'tap', str(x), str(y)], timeout=10)
                time.sleep(2)

                # 验证展开结果
                xml = dump_ui(self.adb_port)
                verify_info = find_all_tracks(xml)
                if track_name in verify_info:
                    self._log(f"展开验证: {track_name}={'已展开' if verify_info[track_name]['expanded'] else '未展开'}")
        else:
            self._log(f"未找到 {track_name} 元素")

        # 6. 滚动查找周序号
        self._log(f"查找 {week_num}...")
        screen_center = self.screen_height // 2
        for scroll_attempt in range(3):
            xml = dump_ui(self.adb_port)
            week_bounds, _, _ = find_week_in_track(xml, week_num, track_name)
            if week_bounds:
                week_cy = (week_bounds[1] + week_bounds[3]) // 2
                if 200 < week_bounds[1] and week_bounds[3] < 2360:
                    self._log(f"{week_num} 已在屏幕范围内")
                    break
                scroll_distance = week_cy - screen_center
                if scroll_distance > 0:
                    run_adb_command([ADB_EXE, '-s', self.adb_port, 'shell', 'input', 'swipe', '720', '1800', '720', str(1800 - min(scroll_distance, 800)), '300'], timeout=10)
                else:
                    run_adb_command([ADB_EXE, '-s', self.adb_port, 'shell', 'input', 'swipe', '720', '800', '720', str(800 + min(abs(scroll_distance), 800)), '300'], timeout=10)
                time.sleep(2)

        # 7. 截图前确认赛道展开
        xml = dump_ui(self.adb_port)
        tracks_info = find_all_tracks(xml)
        if track_name in tracks_info and not tracks_info[track_name]['expanded']:
            self._log(f"截图前赛道未展开，重新展开")
            bounds = tracks_info[track_name]['bounds']
            run_adb_command([ADB_EXE, '-s', self.adb_port, 'shell', 'input', 'tap', '300', str((bounds[1] + bounds[3]) // 2)], timeout=10)
            time.sleep(1.5)
        elif track_name in tracks_info:
            self._log(f"截图前确认: {track_name} 已展开")
        else:
            self._log(f"截图前未找到 {track_name}，直接截图")

        # 8. 截图
        screenshot1 = self.screenshot.take_screenshot(f"{store_name}_{user_name}_{username}_晨读.png")
        return bool(screenshot1), screenshot1

    def execute_second_course(self, account_type, screenshot1, store_name, user_name, username):
        """大练兵截图"""
        self._log("进入大练兵...")

        # 1. 返回
        self.ui.tap(COORDS["back_button"][0], COORDS["back_button"][1], 1)
        time.sleep(1)

        # 2. 搜索
        self.ui.tap(COORDS["search_bar"][0], COORDS["search_bar"][1], 0.5)
        for _ in range(3):
            self.ui.tap(COORDS["search_bar"][0], COORDS["search_bar"][1], 0.1)
        time.sleep(0.5)
        self.ui.keyevent("KEYCODE_DEL", 1)
        time.sleep(1)

        self.ui.input_text(COORDS["search_bar"][0], COORDS["search_bar"][1], f"{account_type}大练兵", 1)
        time.sleep(1)
        self.ui.keyevent("KEYCODE_ENTER", 1)

        if not wait_for_elements(self.adb_port, ["综合", "智能排序", "课程", "Course(s)", "Match"], timeout=15, wait_after_found=3):
            self._log("搜索结果超时")

        # 3. 点击课程
        self.ui.tap(COORDS["first_course"][0], COORDS["first_course"][1], 1)

        # 等待课程详情页加载
        for i in range(10):
            xml = dump_ui(self.adb_port)
            if "班级简介" in xml and "日程表" in xml:
                self._log(f"课程详情页已加载 ({i+1}次检测)")
                break
            self._log(f"等待课程详情页... ({i+1}/10)")
            time.sleep(2)
        else:
            self._log("课程详情页加载超时，继续尝试")

        # 4. 点击日程表（带重试）
        schedule_clicked = False
        for attempt in range(3):
            if self.tap_and_wait(COORDS["schedule_tab"], ["日程由近到远", "已完成", "Schedule", "学习截止时间"], timeout=8, wait_after_found=3, desc="日程表"):
                xml = dump_ui(self.adb_port)
                if any(text in xml for text in ["日程由近到远", "已完成", "Schedule", "学习截止时间"]):
                    schedule_clicked = True
                    break
            self._log(f"日程表未加载，重试({attempt+1}/3)")
            self.ui.tap(COORDS["schedule_tab"][0], COORDS["schedule_tab"][1], 1)
            time.sleep(3)

        if not schedule_clicked:
            self._log("日程表点击失败，直接截图")

        # 5. 截图
        screenshot2 = self.screenshot.take_screenshot(f"{store_name}_{user_name}_{username}_大练兵.png")
        if not screenshot2:
            return False, None

        # 6. 合并
        combined = combine_screenshots(screenshot1, screenshot2, store_name, user_name, username)
        return bool(combined), combined

    def _is_on_home_page(self) -> bool:
        """检测当前是否在主页（中英文界面均支持）"""
        xml = dump_ui(self.adb_port)
        home_markers = ["首页", "学习中心", "Courses", "To do", "Home", "Learning"]
        found = [t for t in home_markers if t in xml]
        self._log(f"主页检测: xml长度={len(xml)}, 命中={found}")
        return bool(found)

    def execute_return_home(self):
        """返回主页，两次返回后直接认为到达主页"""
        self._log("返回主页...")

        # 点击两次左上角返回按钮
        self._log("点击返回按钮 (1/2)")
        self.ui.tap(100, 120, 2)
        self._log("点击返回按钮 (2/2)")
        self.ui.tap(100, 120, 2)
        self._log("两次返回完成，跳过 dump_ui 检测")
        return True

    def _tap_and_wait_hybrid(self, coord, expected_texts, activity_targets=None, timeout=10, wait_after_found=3, desc=""):
        """点击并等待：先尝试 XML 检测，失败时用 Activity 检测兜底"""
        self._log(f"点击 {desc or coord}")
        self.ui.tap(coord[0], coord[1], 1)
        self._log(f"点击完成，等待元素: {expected_texts}")

        start = time.time()
        while time.time() - start < timeout:
            xml = dump_ui(self.adb_port)
            if xml:
                for text in expected_texts:
                    if text in xml:
                        self._log(f"检测到: {text}")
                        if wait_after_found > 0:
                            time.sleep(wait_after_found)
                        return True
            if activity_targets:
                current = get_current_activity(self.adb_port)
                for target in activity_targets:
                    if target in current:
                        self._log(f"检测到 Activity: {current}")
                        if wait_after_found > 0:
                            time.sleep(wait_after_found)
                        return True
            time.sleep(2)

        self._log(f"未检测到: {expected_texts}")
        return False

    def execute_logout(self):
        """退出账号 - 直接调用 subprocess，绕过 ADBManager"""
        try:
            self._log("退出账号...")

            steps = [
                ("我的", COORDS["my_tab"]),
                ("设置", COORDS["settings"]),
                ("退出账号", COORDS["logout_button"]),
                ("确认退出", COORDS["logout_confirm"]),
            ]

            for desc, coord in steps:
                self._log(f"点击 {desc}")
                cmd = [ADB_EXE, '-s', self.adb_port, 'shell', 'input', 'tap', str(coord[0]), str(coord[1])]
                try:
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                except subprocess.TimeoutExpired:
                    self._log(f"点击 {desc} 超时")
                except Exception as e:
                    self._log(f"点击 {desc} 失败: {e}")
                time.sleep(3)

            self._log("退出流程完成")
            return True
        except Exception as e:
            import traceback
            self._log(f"退出流程异常: {e}\n{traceback.format_exc()}")
            return False

    def restart_app(self):
        """重启应用"""
        package = self.config.get("app_package", "com.huawei.iretail.ma")
        activity = self.config.get("app_activity", "com.huawei.iretail.salesassistant.splash.SplashActivity")
        run_adb_command([ADB_EXE, '-s', self.adb_port, 'shell', 'am', 'force-stop', package], timeout=10)
        time.sleep(2)
        run_adb_command([ADB_EXE, '-s', self.adb_port, 'shell', 'am', 'start', '-n', f'{package}/{activity}'], timeout=10)
        time.sleep(5)

    def run_accounts(self, accounts: List[Dict], batch_size: int = 30):
        """批量处理账号"""
        self._log("=== 开始批量处理 ===")

        # 确保 ADB 已连接
        if not self.adb.connect_device():
            self._log(f"ADB 连接失败: {self.adb_port}，请检查模拟器是否启动")
            return []

        results = []
        consecutive_failures = 0
        app_started = False

        for index, account in enumerate(accounts, 1):
            self._check_stopped()

            # 必须用 run_adb_with_output：run_adb_command 丢弃 stdout，会导致断连判断永远成立
            check_cmd = run_adb_with_output([ADB_EXE, '-s', self.adb_port, 'get-state'], timeout=5)
            if check_cmd.returncode != 0 or check_cmd.stdout.strip() != b"device":
                self._log("ADB 设备断开，尝试重连...")
                time.sleep(3)
                if not self.adb.connect_device():
                    self._log(f"重连失败，跳过账号 {account.get('username')}")
                    results.append({"username": account["username"], "success": False, "status": "adb_disconnect", "message": "ADB断连"})
                    continue
                self._log("重连成功")
                app_started = False

            username = account["username"]
            password = account["password"]
            account_type = account.get("account_type", "个人消费")
            user_name = account.get("user_name", "")
            store_name = account.get("store_name", "")
            self._log(f"处理 {index}/{len(accounts)}: {store_name} {user_name} {username}")

            result = {"username": username, "store_name": store_name, "user_name": user_name,
                      "account_type": account_type, "success": False, "status": "failed",
                      "screenshot": None, "message": ""}

            try:
                if not app_started:
                    self.restart_app()
                    app_started = True

                login_result = self.execute_login(username, password)
                if login_result == "login_failed":
                    result.update({"status": "login_failed", "message": "账号或密码错误"})
                    consecutive_failures += 1
                    self.restart_app()
                    if consecutive_failures >= 5:
                        self._log(f"连续 {consecutive_failures} 次登录失败，提前终止")
                        break
                    continue
                if login_result == "password_expire":
                    result.update({"status": "password_expire", "message": "密码即将到期"})
                elif not login_result:
                    result.update({"status": "login_timeout", "message": "登录超时"})
                    self.restart_app()
                    continue
                consecutive_failures = 0

                ok1, screenshot1 = self.execute_first_course(account_type, store_name, user_name, username)
                if not ok1:
                    result.update({"status": "screenshot_failed", "message": "晨读截图失败"})
                    self.restart_app()
                    continue

                ok2, combined = self.execute_second_course(account_type, screenshot1, store_name, user_name, username)
                if not ok2:
                    result.update({"status": "screenshot_failed", "message": "大练兵截图失败"})
                    self.restart_app()
                    continue

                result.update({"success": True, "status": "screenshot_ok", "screenshot": combined, "message": "截图完成"})
                metadata_item = {"username": username, "store_name": store_name,
                                 "user_name": user_name, "account_type": account_type,
                                 "screenshot": combined}
                self.metadata.append(metadata_item)
                if self.screenshot_callback:
                    self.screenshot_callback(metadata_item)
            except Exception as e:
                import traceback
                self._log(f"异常: {traceback.format_exc()}")
                result.update({"status": "exception", "message": str(e)})
            finally:
                try:
                    if not self.execute_return_home():
                        self._log("返回主页失败，跳过退出登录")
                    else:
                        if not self.execute_logout():
                            self._log("退出登录失败")
                except Exception as e:
                    import traceback
                    self._log(f"退出流程异常: {e}\n{traceback.format_exc()}")
                results.append(result)

            if batch_size and index % batch_size == 0:
                self._log(f"已处理 {index} 个账号，重启 app")
                self.restart_app()
                app_started = True

        metadata_path = self.run_dir / "screenshot_metadata.json"
        metadata_path.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return results

    def close(self):
        pass
