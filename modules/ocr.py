import re
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List


def get_current_week() -> int:
    today = datetime.now()
    day_of_year = today.timetuple().tm_yday
    if day_of_year <= 4:
        return 1
    return (day_of_year - 5) // 7 + 2


def parse_course_date(value: str):
    match = re.fullmatch(r"(20\d{2})-(\d{1,2})-(\d{1,2})", value.strip())
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).date()
    except ValueError:
        return None


class LearningOCR:
    def __init__(self, log_callback=None, workers: int = 1):
        self.log_callback = log_callback
        self.workers = max(1, int(workers or 1))
        self._ocr = None

    def _log(self, message: str):
        if self.log_callback:
            self.log_callback(message)

    def _engine(self):
        if self._ocr is None:
            os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "modelscope")
            os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")
            os.environ.setdefault("FLAGS_use_mkldnn", "0")
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise RuntimeError("OCR 依赖 paddleocr 未安装，请安装 windows/requirements.txt 中的依赖或关闭 OCR") from exc
            self._ocr = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang="ch",
            )
        return self._ocr

    def _ocr_lines(self, image_path: str):
        engine = self._engine()
        try:
            result = engine.ocr(image_path, cls=True)
        except TypeError:
            result = engine.ocr(image_path)
        lines = []
        for page in result or []:
            if isinstance(page, dict) and "rec_texts" in page:
                texts = page.get("rec_texts") or []
                scores = page.get("rec_scores") or []
                boxes = page.get("rec_polys") or page.get("dt_polys") or []
                for index, text in enumerate(texts):
                    bounds = boxes[index] if index < len(boxes) else []
                    score = scores[index] if index < len(scores) else 0
                    points = [list(point) for point in bounds] if bounds is not None else []
                    if not points:
                        continue
                    xs = [point[0] for point in points]
                    ys = [point[1] for point in points]
                    lines.append({
                        "text": text,
                        "score": score,
                        "bounds": points,
                        "center_x": sum(xs) / len(xs),
                        "center_y": sum(ys) / len(ys),
                    })
                continue

            if hasattr(page, "json"):
                data = page.json() if callable(page.json) else page.json
                texts = data.get("rec_texts") or []
                scores = data.get("rec_scores") or []
                boxes = data.get("rec_polys") or data.get("dt_polys") or []
                for index, text in enumerate(texts):
                    bounds = boxes[index] if index < len(boxes) else []
                    score = scores[index] if index < len(scores) else 0
                    points = [list(point) for point in bounds] if bounds is not None else []
                    if not points:
                        continue
                    xs = [point[0] for point in points]
                    ys = [point[1] for point in points]
                    lines.append({
                        "text": text,
                        "score": score,
                        "bounds": points,
                        "center_x": sum(xs) / len(xs),
                        "center_y": sum(ys) / len(ys),
                    })
                continue

            for item in page or []:
                if not item or len(item) < 2:
                    continue
                bounds = item[0]
                text = item[1][0]
                score = item[1][1]
                xs = [point[0] for point in bounds]
                ys = [point[1] for point in bounds]
                lines.append({
                    "text": text,
                    "score": score,
                    "bounds": bounds,
                    "center_x": sum(xs) / len(xs),
                    "center_y": sum(ys) / len(ys),
                })
        return lines

    def _check_chendu_by_color(self, image_path: str, lines: List[Dict], week_num: int) -> str:
        """通过W序号前面符号的颜色判断晨读是否完成"""
        week_text = f"W{week_num}"
        if not lines:
            return f"未完成({week_text}未找到)"
        
        # 查找W序号位置
        week_line = None
        for line in lines:
            if week_text in line["text"].replace(" ", ""):
                week_line = line
                break
        
        if not week_line:
            return f"未完成({week_text}未找到)"
        
        try:
            from PIL import Image
            img = Image.open(image_path)
            
            week_x = int(week_line["center_x"])
            week_y = int(week_line["center_y"])
            
            # 扫描W序号左侧20-130像素范围，寻找有颜色的标记
            has_green = False
            has_blue_or_gray = False
            
            for offset in range(20, 140, 5):
                sx = week_x - offset
                if sx < 0 or sx >= img.width:
                    continue
                
                # 采样上下几行的像素
                for dy in range(-15, 20, 5):
                    sy = week_y + dy
                    if sy < 0 or sy >= img.height:
                        continue
                    
                    r, g, b = img.getpixel((sx, sy))[:3]
                    
                    # 绿色标记：G通道最高且明显
                    if g > 100 and g > r and g > b * 0.9:
                        has_green = True
                    # 蓝色标记：B通道高
                    elif b > 150 and b > r * 1.5 and b > g * 1.5:
                        has_blue_or_gray = True
                    # 灰色标记：各通道相近且不是白色
                    elif 50 < r < 200 and 50 < g < 200 and 50 < b < 200 and abs(r-g) < 30 and abs(g-b) < 30:
                        has_blue_or_gray = True
            
            if has_green:
                return f"已完成({week_text}绿色标记)"
            else:
                return f"未完成({week_text}非绿色标记)"
                
        except Exception as e:
            return f"未完成({week_text}颜色检测失败: {e})"

    def check_chendu(self, image_path: str, week_num: int) -> str:
        lines = self._ocr_lines(image_path)
        return self._check_chendu_by_color(image_path, lines, week_num)

    def _check_dalianbing_lines(self, lines: List[Dict]) -> str:
        today = datetime.now()
        week_end = (today + timedelta(days=(6 - today.weekday()))).date()

        found_valid_course = False
        has_unfinished = False
        has_finished = False
        date_pattern = re.compile(r"20\d{2}-\d{1,2}-\d{1,2}")
        # 状态标记（支持中英文和带空格的情况）
        unfinished_markers = ["To Learn", "去学习", "去 学 习", "未完成", "未 完 成", "待学习", "待 学 习"]
        finished_markers = ["Completed", "已完成", "完 成", "已完成学习", "已 完 成"]
        # 大练兵在合成图右半边(x≥1400)，排除非课程元信息行
        metadata_keywords = ["开班时间", "结班时间", "场次", "日程表学习截止时间"]

        # 按垂直位置排序，从上到下扫描，只看右半边（大练兵区域）
        sorted_lines = sorted(lines, key=lambda item: item["center_y"])

        for index, line in enumerate(sorted_lines):
            # 只看合成图右半边（大练兵区域），排除左侧晨读区的日期
            if line["center_x"] < 1400:
                continue
            # 跳过开班时间/结班时间/场次等非课程元信息行
            if any(kw in line["text"] for kw in metadata_keywords):
                continue
            match = date_pattern.search(line["text"])
            if not match:
                continue
            course_date = parse_course_date(match.group(0))
            if not course_date or course_date > week_end:
                continue
            found_valid_course = True
            # 检查当前行及后续几行的状态标记
            block_text = " ".join(item["text"] for item in sorted_lines[index:index + 10])
            block_text_no_space = block_text.replace(" ", "")

            if any(marker in block_text or marker.replace(" ", "") in block_text_no_space for marker in unfinished_markers):
                has_unfinished = True
            if any(marker in block_text or marker.replace(" ", "") in block_text_no_space for marker in finished_markers):
                has_finished = True

        if has_unfinished:
            return "未完成"
        if has_finished and found_valid_course:
            return "已完成"
        if found_valid_course:
            # 找到日期但无状态标记（OCR漏读或截图未拍到）→ 保守判未完成
            return "未完成(无状态标记)"
        return "未完成(未识别到本周课程)"

    def check_dalianbing(self, image_path: str) -> str:
        return self._check_dalianbing_lines(self._ocr_lines(image_path))

    def _analyze_item(self, item: Dict, week_num: int) -> Dict:
        image_path = item.get("screenshot")
        if not image_path or not Path(image_path).exists():
            chendu = "未完成(无截图)"
            dalianbing = "未完成(无截图)"
        else:
            try:
                lines = self._ocr_lines(image_path)
                chendu = self._check_chendu_by_color(image_path, lines, week_num)
                dalianbing = self._check_dalianbing_lines(lines)
            except Exception as e:
                self._log(f"OCR失败 {item.get('username')}: {e}")
                chendu = "未完成(OCR失败)"
                dalianbing = "未完成(OCR失败)"

        chendu_done = chendu.startswith("已完成") or chendu.startswith("Completed")
        dalianbing_done = dalianbing.startswith("已完成") or dalianbing.startswith("Completed")
        overall = "已完成" if chendu_done and dalianbing_done else "未完成"

        return {
            "username": item.get("username", ""),
            "store_name": item.get("store_name", ""),
            "user_name": item.get("user_name", ""),
            "account_type": item.get("account_type", ""),
            "screenshot": image_path,
            "chendu": chendu,
            "dalianbing": dalianbing,
            "overall": overall,
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def results_from_details(details: List[Dict], week_num: int) -> Dict:
        completed = len([item for item in details if item.get("overall") == "已完成"])
        uncompleted = len(details) - completed
        return {
            "timestamp": datetime.now().isoformat(),
            "current_week": week_num,
            "total": len(details),
            "completed": completed,
            "uncompleted": uncompleted,
            "details": details,
        }

    def analyze_item(self, item: Dict, week_num: int = None) -> Dict:
        return self._analyze_item(item, week_num or get_current_week())

    def analyze(self, metadata: List[Dict]) -> Dict:
        week_num = get_current_week()
        if self.workers > 1 and len(metadata) > 1:
            self._log(f"OCR 并行分析: workers={self.workers}")

            def analyze_with_local_engine(item: Dict) -> Dict:
                local_ocr = LearningOCR(log_callback=self.log_callback, workers=1)
                return local_ocr._analyze_item(item, week_num)

            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                details = list(executor.map(analyze_with_local_engine, metadata))
        else:
            details = [self._analyze_item(item, week_num) for item in metadata]

        return self.results_from_details(details, week_num)
