from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from contract import (
    ARCHIVE_SCHEMA_VERSION,
    dump_json,
    entry_time_within_cutoff,
    format_datetime,
    hash_file,
    normalize_extension,
    normalize_filename_key,
    normalize_text,
    now_text,
    parse_datetime_text,
    parse_submission_content,
    sanitize_filename_component,
)


def build_output_filename(student: dict[str, str], ext: str) -> str:
    return sanitize_filename_component(f"{student['学号']}{student['姓名']}{ext}")


def archive_version_id(entry_data: dict[str, Any]) -> str:
    seed = "|".join(
        [
            str(entry_data.get("学号", "")),
            str(entry_data.get("提交序号", "")),
            str(entry_data.get("提交内容", "")),
            str(entry_data.get("提交时间", "")),
            str(entry_data.get("源附件名", "")),
            str(entry_data.get("状态", "")),
            str(entry_data.get("sha256") or entry_data.get("hash") or ""),
            str(entry_data.get("原因", "")),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def archive_entry_token(entry_id: str) -> str:
    digest = hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:16]
    readable = sanitize_filename_component(entry_id.replace("|", "_"))[:80]
    return f"{readable}-{digest}" if readable else digest


def archive_version_token(version: dict[str, Any]) -> str:
    timestamp = re.sub(r"[^0-9]", "", str(version.get("提交时间", ""))) or "unknown-time"
    return f"{timestamp}-{str(version.get('id', archive_version_id(version)))[:12]}"


def immutable_version_path(course_out_dir: Path, entry_id: str, version: dict[str, Any], filename: str) -> Path:
    return (
        course_out_dir
        / "files"
        / "_versions"
        / archive_entry_token(entry_id)
        / archive_version_token(version)
        / sanitize_filename_component(filename)
    )


def base_entry_from_data(entry_id: str, data: dict[str, Any], meta: dict[str, str]) -> dict[str, Any]:
    return {
        "id": entry_id,
        "收集表ID": meta["收集表ID"],
        "标题": meta["标题"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "学号": str(data.get("学号", "")).strip(),
        "姓名": str(data.get("姓名") or data.get("学生") or "").strip(),
        "班级": str(data.get("班级", "")).strip(),
        "提交序号": str(data.get("提交序号", "")).strip(),
        "提交内容": str(data.get("提交内容", "")).strip(),
        "提交内容名": str(data.get("提交内容名", "")).strip(),
        "允许后缀": list(data.get("允许后缀", [])),
        "versions": [],
    }


def version_from_data(data: dict[str, Any], *, source: str, archive_origin: str = "excel_sync") -> dict[str, Any]:
    status = str(data.get("状态", "")).strip() or "missing"
    version = {
        "状态": status,
        "原因": str(data.get("原因", "")).strip(),
        "提交时间": str(data.get("提交时间", "")).strip(),
        "源附件名": str(data.get("源附件名", "")).strip(),
        "用户类型": str(data.get("用户类型", "")).strip(),
        "文件相对路径": str(data.get("文件相对路径") or data.get("文件路径") or "").strip().replace("\\", "/"),
        "文件大小": data.get("文件大小", data.get("大小", 0)),
        "sha256": str(data.get("sha256") or data.get("hash") or "").strip(),
        "归档更新时间": str(data.get("归档更新时间") or now_text()).strip(),
        "归档来源": archive_origin,
        "版本来源": source,
    }
    if data.get("同步源已删除但保留归档"):
        version["同步源已删除但保留归档"] = True
    version["id"] = archive_version_id({**data, **version})
    return version


def merged_entry_version(entry: dict[str, Any], version: dict[str, Any]) -> dict[str, Any]:
    merged = {k: v for k, v in entry.items() if k != "versions"}
    merged.update(version)
    return merged


def version_sort_key(version: dict[str, Any]) -> tuple[pd.Timestamp, str]:
    ts = parse_datetime_text(version.get("提交时间"))
    return (ts if ts is not None else pd.Timestamp.min, str(version.get("id", "")))


def update_entry_latest_fields(entry: dict[str, Any], version: dict[str, Any]) -> None:
    for key in [
        "状态",
        "原因",
        "提交时间",
        "源附件名",
        "用户类型",
        "文件相对路径",
        "文件大小",
        "sha256",
        "归档更新时间",
        "归档来源",
        "版本来源",
    ]:
        if key in version:
            entry[key] = version[key]
    entry["最新版本"] = version.get("id", "")


def append_archive_version(entry: dict[str, Any], version: dict[str, Any]) -> None:
    versions = entry.setdefault("versions", [])
    if not isinstance(versions, list):
        raise ValueError(f"归档版本列表无效: {entry.get('id')}")
    existing_index = next((idx for idx, item in enumerate(versions) if item.get("id") == version.get("id")), None)
    if existing_index is None:
        versions.append(version)
    else:
        versions[existing_index] = {**versions[existing_index], **version}
    versions.sort(key=version_sort_key)
    update_entry_latest_fields(entry, versions[-1])


def active_version_file_exists(course_out_dir: Path, version: dict[str, Any]) -> bool:
    if version.get("状态") != "active":
        return False
    rel = str(version.get("文件相对路径", "")).strip()
    return bool(rel) and (course_out_dir / rel).is_file()


def has_active_archived_file(entry: dict[str, Any], course_out_dir: Path) -> bool:
    return any(active_version_file_exists(course_out_dir, version) for version in entry.get("versions", []))


def ensure_version_file(
    course_out_dir: Path,
    entry_id: str,
    version: dict[str, Any],
    source_path: Path,
    output_filename: str,
) -> None:
    target = immutable_version_path(course_out_dir, entry_id, version, output_filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(source_path, target)
    version["文件相对路径"] = str(target.relative_to(course_out_dir)).replace("\\", "/")
    version["文件大小"] = target.stat().st_size
    version["sha256"] = hash_file(target)


def load_archive_manifest(archive_path: Path, meta: dict[str, str]) -> dict[str, Any]:
    if archive_path.exists():
        data = json.loads(archive_path.read_text(encoding="utf-8"))
        schema_version = data.get("schema_version")
        if schema_version != ARCHIVE_SCHEMA_VERSION:
            raise ValueError(f"归档 manifest 版本不支持: {archive_path}")
        entries = data.get("entries")
        if not isinstance(entries, dict):
            raise ValueError(f"归档 manifest entries 无效: {archive_path}")
        for entry_id, entry in entries.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("versions"), list):
                raise ValueError(f"归档 manifest entry 缺少 versions: {archive_path} -> {entry_id}")
        return data
    return {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "收集表ID": meta["收集表ID"],
        "标题": meta["标题"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "状态": meta.get("状态", "active"),
        "created_at": now_text(),
        "updated_at": now_text(),
        "entries": {},
    }


def archive_entry_id(student_no: str, submission_label: str, content_label: str) -> str:
    return "|".join([student_no, submission_label, content_label])


def active_archive_path(
    course_out_dir: Path,
    submission_label: str,
    content_name: str,
    class_name: str,
    filename: str,
) -> Path:
    return (
        course_out_dir
        / "files"
        / "current"
        / sanitize_filename_component(submission_label)
        / sanitize_filename_component(content_name)
        / sanitize_filename_component(class_name)
        / filename
    )


def history_archive_path(course_out_dir: Path, entry: dict[str, Any]) -> Path:
    timestamp = re.sub(r"[^0-9]", "", str(entry.get("提交时间", ""))) or datetime.now().strftime("%Y%m%d%H%M%S")
    filename = Path(str(entry.get("文件相对路径", "old-file"))).name
    return (
        course_out_dir
        / "history"
        / sanitize_filename_component(str(entry.get("提交序号", "未知提交")))
        / sanitize_filename_component(str(entry.get("提交内容名", "未知内容")))
        / sanitize_filename_component(str(entry.get("学号", "未知学生")))
        / f"{timestamp}-{filename}"
    )


def retire_existing_active_file(course_out_dir: Path, entry: dict[str, Any]) -> None:
    rel = str(entry.get("文件相对路径", "")).strip()
    if not rel:
        return
    old_path = (course_out_dir / rel).resolve()
    if not old_path.exists() or not old_path.is_file():
        return
    history_path = history_archive_path(course_out_dir, entry)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    if history_path.exists():
        history_path = history_path.with_name(f"{history_path.stem}-{hash_file(old_path)[:8]}{history_path.suffix}")
    shutil.move(str(old_path), str(history_path))
    entry.setdefault("历史文件", []).append(str(history_path.relative_to(course_out_dir)).replace("\\", "/"))


def upsert_active_file(
    manifest: dict[str, Any],
    course_out_dir: Path,
    entry_id: str,
    source_path: Path,
    destination_path: Path,
    entry_data: dict[str, Any],
) -> None:
    existing = manifest["entries"].get(entry_id)
    entry = existing if isinstance(existing, dict) else base_entry_from_data(entry_id, entry_data, manifest)
    version = version_from_data({**entry_data, "状态": "active"}, source="excel_sync")
    ensure_version_file(course_out_dir, entry_id, version, source_path, destination_path.name)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    version_source = course_out_dir / str(version["文件相对路径"])
    if not destination_path.exists() or hash_file(destination_path) != version["sha256"]:
        shutil.copy2(version_source, destination_path)
    append_archive_version(entry, version)
    manifest["entries"][entry_id] = entry


def set_non_active_status(
    manifest: dict[str, Any],
    course_out_dir: Path,
    entry_id: str,
    entry_data: dict[str, Any],
    status: str,
    reason: str,
) -> None:
    existing = manifest["entries"].get(entry_id)
    entry = existing if isinstance(existing, dict) else base_entry_from_data(entry_id, entry_data, manifest)
    version = version_from_data(
        {
            **entry_data,
            "状态": status,
            "原因": reason,
            "归档更新时间": now_text(),
        },
        source="excel_sync",
    )
    append_archive_version(entry, version)
    manifest["entries"][entry_id] = entry


def latest_rows_by_key(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.sort_values(by="_record_time")
        .drop_duplicates(subset=["_submission_label", "_content_label", "_name_norm"], keep="last")
        .copy()
    )


def merge_incremental_archive(
    *,
    df: pd.DataFrame,
    columns: dict[str, str],
    meta: dict[str, str],
    selected_labels: list[str],
    course_out_dir: Path,
    attachments_dir: Path,
    attachment_lookup: dict[str, str],
    duplicate_lookup: dict[str, list[str]],
    students_by_name: dict[str, dict[str, str]],
    other_students_by_name: dict[str, dict[str, str]],
) -> dict[str, Any]:
    archive_path = course_out_dir / "archive_manifest.json"
    manifest = load_archive_manifest(archive_path, meta)
    selected_set = set(selected_labels)
    selected_df = df[df["_submission_label"].isin(selected_set)].copy()
    selected_df = selected_df.sort_values(by="_record_time")

    for _, row in selected_df.iterrows():
        name_norm = row["_name_norm"]
        student = students_by_name.get(name_norm) or other_students_by_name.get(name_norm)
        if student is None:
            continue
        content = parse_submission_content(row["_content_label"])
        uploaded_name = str(row["_uploaded_filename"]).strip()
        uploaded_ext = normalize_extension(Path(uploaded_name).suffix)
        submission_label = str(row["_submission_label"])
        content_label = str(row["_content_label"])
        entry_id = archive_entry_id(student["学号"], submission_label, content_label)
        base_entry = {
            "id": entry_id,
            "收集表ID": meta["收集表ID"],
            "标题": meta["标题"],
            "主题": meta["主题"],
            "对象": meta["对象"],
            "周期": meta["周期"],
            "学号": student["学号"],
            "姓名": student["姓名"],
            "班级": student["班级"],
            "提交序号": submission_label,
            "提交内容": content_label,
            "提交内容名": content["提交内容名"],
            "允许后缀": list(content["允许后缀"]),
            "提交时间": format_datetime(row[columns["time"]]),
            "源附件名": uploaded_name,
            "用户类型": normalize_text(row[columns["user_type"]]),
        }

        if not uploaded_name:
            set_non_active_status(manifest, course_out_dir, entry_id, base_entry, "missing", "上传字段为空")
            continue
        if uploaded_ext not in content["允许后缀"]:
            set_non_active_status(
                manifest,
                course_out_dir,
                entry_id,
                base_entry,
                "invalid",
                f"后缀 {uploaded_ext or '无后缀'} 不符合 {content_label}",
            )
            continue

        file_key = normalize_filename_key(uploaded_name)
        if file_key in duplicate_lookup:
            base_entry["本地候选附件名"] = duplicate_lookup[file_key]
            set_non_active_status(manifest, course_out_dir, entry_id, base_entry, "missing", "本地附件名存在歧义")
            continue

        source_filename = attachment_lookup.get(file_key, "")
        existing = manifest["entries"].get(entry_id)
        if not source_filename:
            if isinstance(existing, dict) and has_active_archived_file(existing, course_out_dir):
                for version in existing.get("versions", []):
                    if active_version_file_exists(course_out_dir, version):
                        version["同步源已删除但保留归档"] = True
                manifest["entries"][entry_id] = existing
            else:
                set_non_active_status(manifest, course_out_dir, entry_id, base_entry, "missing", "本地同步目录未找到附件")
            continue

        source_path = attachments_dir / source_filename
        if not source_path.exists():
            if isinstance(existing, dict) and has_active_archived_file(existing, course_out_dir):
                for version in existing.get("versions", []):
                    if active_version_file_exists(course_out_dir, version):
                        version["同步源已删除但保留归档"] = True
                manifest["entries"][entry_id] = existing
            else:
                set_non_active_status(manifest, course_out_dir, entry_id, base_entry, "missing", "源附件路径不存在")
            continue

        ext = normalize_extension(source_path.suffix)
        if ext not in content["允许后缀"]:
            set_non_active_status(
                manifest,
                course_out_dir,
                entry_id,
                base_entry,
                "invalid",
                f"实际后缀 {ext or '无后缀'} 不符合 {content_label}",
            )
            continue

        destination = active_archive_path(
            course_out_dir,
            submission_label,
            content["提交内容名"],
            student["班级"],
            build_output_filename(student, ext),
        )
        upsert_active_file(manifest, course_out_dir, entry_id, source_path, destination, base_entry)

    manifest["updated_at"] = now_text()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(dump_json(manifest), encoding="utf-8")
    return manifest


def active_entry_for(
    manifest: dict[str, Any],
    student_no: str,
    submission_label: str,
    content_label: str,
    cutoff: pd.Timestamp | None = None,
) -> dict[str, Any] | None:
    entry = manifest.get("entries", {}).get(archive_entry_id(student_no, submission_label, content_label))
    if not isinstance(entry, dict):
        return None
    versions = [
        version
        for version in entry.get("versions", [])
        if isinstance(version, dict) and entry_time_within_cutoff(version, cutoff)
    ]
    if not versions:
        return None
    return merged_entry_version(entry, sorted(versions, key=version_sort_key)[-1])


def latest_version_after_cutoff(
    manifest: dict[str, Any],
    student_no: str,
    submission_label: str,
    content_label: str,
    cutoff: pd.Timestamp | None,
) -> dict[str, Any] | None:
    if cutoff is None:
        return None
    entry = manifest.get("entries", {}).get(archive_entry_id(student_no, submission_label, content_label))
    if not isinstance(entry, dict):
        return None
    versions = []
    for version in entry.get("versions", []):
        if not isinstance(version, dict):
            continue
        ts = parse_datetime_text(version.get("提交时间"))
        if ts is not None and ts > cutoff:
            versions.append(version)
    if not versions:
        return None
    return merged_entry_version(entry, sorted(versions, key=version_sort_key)[-1])
