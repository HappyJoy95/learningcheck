"""
上传模块 - 推送学习检查报告到远程服务器（HTTP API方式）
使用 MCP server 的 /api/upload 接口
"""
import hashlib
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get_upload_config(config: Dict) -> Optional[Dict]:
    upload_cfg = config.get("upload", {})
    if not upload_cfg or not upload_cfg.get("enabled"):
        return None
    required = ["mcp_host", "mcp_port", "remote_path"]
    missing = [k for k in required if not upload_cfg.get(k)]
    if missing:
        return None
    return upload_cfg


def _upload_file(
    local_path: Path,
    remote_path: str,
    upload_cfg: Dict,
    max_retries: int = 3,
) -> bool:
    host = upload_cfg["mcp_host"]
    port = upload_cfg["mcp_port"]
    owner_key = upload_cfg.get("owner_key", "")
    upload_url = f"http://{host}:{port}/api/upload"

    with open(local_path, "rb") as f:
        content = f.read()
    local_sha = _sha256(content)

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.put(
                upload_url,
                params={
                    "path": remote_path,
                    "sha256": local_sha,
                    "auth_key": owner_key,
                },
                data=content,
                timeout=30,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("success"):
                    if result.get("sha256") == local_sha:
                        return True
                    last_error = "SHA256校验不匹配"
                else:
                    last_error = result.get("error", "上传失败")
            else:
                last_error = f"HTTP {resp.status_code}"
        except Exception as e:
            last_error = str(e)

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    print(f"[upload] 失败 ({remote_path}): {last_error}")
    return False


def upload_reports(
    run_dir: Path,
    config: Dict,
    log_callback: Optional[Callable] = None,
) -> bool:
    def log(msg):
        if log_callback:
            log_callback(msg)

    upload_cfg = _get_upload_config(config)
    if not upload_cfg:
        log("上传未启用或配置不完整，跳过")
        return False

    execution_report = run_dir / "execution_report.json"
    ocr_results = run_dir / "ocr_results.json"

    if not execution_report.exists():
        log(f"缺少 {execution_report.name}，跳过上传")
        return False
    if not ocr_results.exists():
        log(f"缺少 {ocr_results.name}，跳过上传")
        return False

    run_id = run_dir.name  # e.g. "20260621_003746"
    remote_base = upload_cfg["remote_path"].rstrip("/")
    host = upload_cfg["mcp_host"]
    port = upload_cfg["mcp_port"]

    now = datetime.now()
    week_num = now.isocalendar()[1]

    try:
        files_to_upload = [
            (execution_report, "execution_report.json"),
            (ocr_results, "ocr_results.json"),
        ]

        uploaded = 0
        for local_path, filename in files_to_upload:
            remote_path = f"{remote_base}/{week_num}/{run_id}/{filename}"
            if _upload_file(local_path, remote_path, upload_cfg):
                log(f"已上传: {week_num}/{run_id}/{filename}")
                uploaded += 1
            else:
                log(f"上传失败: {filename}")

        # 写入元信息
        meta = {
            "run_id": run_id,
            "week": week_num,
            "uploaded_at": datetime.now().isoformat(),
            "files": ["execution_report.json", "ocr_results.json"],
        }
        meta_path = f"{remote_base}/{week_num}/{run_id}/.meta.json"
        meta_bytes = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
        meta_sha = _sha256(meta_bytes)

        try:
            resp = requests.put(
                f"http://{host}:{port}/api/upload",
                params={"path": meta_path, "sha256": meta_sha, "auth_key": upload_cfg.get("owner_key", "")},
                data=meta_bytes,
                timeout=30,
            )
        except Exception:
            pass

        log(f"上传完成: {uploaded}/{len(files_to_upload)} → {host}:{port}/{remote_base}/{week_num}/{run_id}/")
        return uploaded > 0

    except Exception as e:
        log(f"上传异常: {e}")
        return False
