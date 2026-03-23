from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"{label} JSON 解析失败: {path}: {err}") from err
    if not isinstance(data, dict):
        raise ValueError(f"{label}格式无效（应为 JSON 对象）: {path}")
    return data


def _cleanup_legacy_hashed_files(public_root: Path) -> None:
    for old_index in public_root.glob("courses.*.json"):
        old_index.unlink()

    data_dir = public_root / "data"
    if not data_dir.exists():
        return

    for old_data in data_dir.glob("*.json"):
        name = old_data.name
        if ".hw" in name or name.endswith(".index.json"):
            continue
        if name.count(".") >= 2:
            old_data.unlink()


def rebuild_course_manifest(public_root: Path, course_index_path: Path) -> dict[str, str]:
    public_root = public_root.expanduser().resolve()
    course_index_path = course_index_path.expanduser().resolve()
    if not course_index_path.exists():
        raise FileNotFoundError(f"找不到课程索引文件: {course_index_path}")

    _cleanup_legacy_hashed_files(public_root)

    index_data = _load_json_object(course_index_path, "课程索引")
    raw_courses = index_data.get("课程列表", [])
    if not isinstance(raw_courses, list):
        raise ValueError("课程索引中的 '课程列表' 必须是数组。")

    hash_input = bytearray()
    hash_input.extend(course_index_path.read_bytes())

    for item in raw_courses:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("数据文件", "")).strip()
        if not rel:
            continue
        course_index_file = (public_root / rel).resolve()
        if not course_index_file.exists():
            raise FileNotFoundError(f"课程索引文件不存在: {rel} ({course_index_file})")
        hash_input.extend(course_index_file.read_bytes())

        course_data = _load_json_object(course_index_file, "课程作业索引")
        homework_list = course_data.get("作业列表", [])
        if not isinstance(homework_list, list):
            continue
        for hw in homework_list:
            if not isinstance(hw, dict):
                continue
            hw_rel = str(hw.get("数据文件", "")).strip()
            if not hw_rel:
                continue
            hw_file = (public_root / hw_rel).resolve()
            if not hw_file.exists():
                raise FileNotFoundError(f"作业数据文件不存在: {hw_rel} ({hw_file})")
            hash_input.extend(hw_file.read_bytes())

    version = _hash_bytes(bytes(hash_input))
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    manifest: dict[str, Any] = {
        "version": version,
        "更新时间": now_text,
        "indexFile": "courses.json",
    }

    deploy_time = index_data.get("最后部署时间")
    if isinstance(deploy_time, str) and deploy_time.strip():
        manifest["最后部署时间"] = deploy_time.strip()

    manifest_path = public_root / "course-manifest.json"
    manifest_path.write_text(_dump_json(manifest), encoding="utf-8")

    return {
        "manifest_file": str(manifest_path),
        "index_file": str(course_index_path),
        "version": version,
    }
