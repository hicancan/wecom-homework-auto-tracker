from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def sanitize_filename_component(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(text)).strip()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _load_index(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"课程索引 JSON 解析失败: {path}: {err}") from err
    if not isinstance(data, dict):
        raise ValueError(f"课程索引格式无效（应为 JSON 对象）: {path}")
    return data


def rebuild_course_manifest(public_root: Path, course_index_path: Path) -> dict[str, str]:
    public_root = public_root.expanduser().resolve()
    course_index_path = course_index_path.expanduser().resolve()
    if not course_index_path.exists():
        raise FileNotFoundError(f"找不到课程索引文件: {course_index_path}")

    index_data = _load_index(course_index_path)
    raw_list = index_data.get("课程列表", [])
    if not isinstance(raw_list, list):
        raise ValueError("课程索引中的 '课程列表' 必须是数组。")

    data_dir = public_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    hashed_courses: list[dict[str, str]] = []
    keep_hashed_data: dict[str, str] = {}

    for item in raw_list:
        if not isinstance(item, dict):
            continue

        course_name = str(item.get("课程", "")).strip()
        source_rel = str(item.get("数据文件", "")).strip()
        if not course_name or not source_rel:
            continue

        source_path = (public_root / source_rel).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"课程数据文件不存在: {source_rel} ({source_path})")

        source_bytes = source_path.read_bytes()
        course_slug = sanitize_filename_component(course_name)
        content_hash = _hash_bytes(source_bytes)
        hashed_filename = f"{course_slug}.{content_hash}.json"
        hashed_rel = f"data/{hashed_filename}"
        hashed_path = data_dir / hashed_filename

        if not hashed_path.exists() or hashed_path.read_bytes() != source_bytes:
            hashed_path.write_bytes(source_bytes)

        keep_hashed_data[course_slug] = hashed_filename
        hashed_courses.append({"课程": course_name, "数据文件": hashed_rel})

    for course_slug, keep_name in keep_hashed_data.items():
        for old_file in data_dir.glob(f"{course_slug}.*.json"):
            if old_file.name == keep_name:
                continue
            old_file.unlink()

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hashed_courses.sort(key=lambda item: item["课程"])
    hashed_index: dict[str, Any] = {"更新时间": now_text, "课程列表": hashed_courses}
    deploy_time = index_data.get("最后部署时间")
    if isinstance(deploy_time, str) and deploy_time.strip():
        hashed_index["最后部署时间"] = deploy_time.strip()

    hashed_index_bytes = _dump_json(hashed_index).encode("utf-8")
    index_hash = _hash_bytes(hashed_index_bytes)
    hashed_index_name = f"courses.{index_hash}.json"
    hashed_index_path = public_root / hashed_index_name
    hashed_index_path.write_bytes(hashed_index_bytes)

    for old_index in public_root.glob("courses.*.json"):
        if old_index.name == hashed_index_name:
            continue
        old_index.unlink()

    manifest: dict[str, Any] = {
        "version": index_hash,
        "更新时间": now_text,
        "indexFile": hashed_index_name,
    }
    if "最后部署时间" in hashed_index:
        manifest["最后部署时间"] = hashed_index["最后部署时间"]

    manifest_path = public_root / "course-manifest.json"
    manifest_path.write_text(_dump_json(manifest), encoding="utf-8")

    return {
        "manifest_file": str(manifest_path),
        "index_file": str(hashed_index_path),
        "version": index_hash,
    }
