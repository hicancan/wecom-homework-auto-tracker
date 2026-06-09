from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from course_manifest import rebuild_course_manifest


TITLE_RE = re.compile(r"^(?P<topic>.+?)\[(?P<audience>[^\[\]]+)\](?:\[(?P<period>[^\[\]]+)\])?$")
CONTENT_RE = re.compile(r"^(?P<name>.+?)\((?P<exts>\.[A-Za-z0-9]+(?:/\.[A-Za-z0-9]+)*)\)$")
ARCHIVE_SCHEMA_VERSION = 2


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_local_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"配置文件 JSON 解析失败: {config_path}: {err}") from err
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 JSON 对象: {config_path}")
    return data


def dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def resolve_path(text: Any, base_dir: Path) -> Path:
    raw = str(text or "").strip()
    if not raw:
        return Path()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def normalize_name(name: Any) -> str:
    return re.sub(r"\s+", "", str(name or "")).strip()


def normalize_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def sanitize_filename_component(text: Any) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(text or "")).strip()


def normalize_extension(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw if raw.startswith(".") else f".{raw}"


def extract_submission_number(label: str) -> int | None:
    match = re.search(r"(\d+)", str(label))
    return int(match.group(1)) if match else None


def sort_submission_key(label: str) -> tuple[int, str]:
    number = extract_submission_number(label)
    return (number if number is not None else 10**9, label)


def parse_collection_title(title: str) -> dict[str, str]:
    match = TITLE_RE.fullmatch(title.strip())
    if not match:
        raise ValueError(f"收集表标题必须符合 主题[对象][周期可选]: {title}")
    topic = match.group("topic").strip()
    audience = match.group("audience").strip()
    period = (match.group("period") or "").strip()
    if not topic or not audience:
        raise ValueError(f"收集表标题的主题和对象不能为空: {title}")
    return {
        "课程": title.strip(),
        "主题": topic,
        "对象": audience,
        "周期": period,
    }


def parse_submission_content(label: str) -> dict[str, Any]:
    text = normalize_text(label)
    match = CONTENT_RE.fullmatch(text)
    if not match:
        raise ValueError(f"提交内容必须符合 内容名(.ext/.ext): {label}")
    name = match.group("name").strip()
    exts = tuple(normalize_extension(ext) for ext in match.group("exts").split("/"))
    if not name or not exts or any(not ext for ext in exts):
        raise ValueError(f"提交内容格式无效: {label}")
    return {
        "提交内容": text,
        "提交内容名": name,
        "允许后缀": tuple(dict.fromkeys(exts)),
    }


def normalize_uploaded_filename(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = raw.replace("\\", "/")
    return cleaned.split("/")[-1].strip()


def normalize_filename_key(filename: str) -> str:
    return str(filename or "").strip().lower()


def format_datetime(value: Any) -> str:
    if pd.isna(value):
        return ""
    return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime_text(value: Any) -> pd.Timestamp | None:
    text = format_datetime(value) if not isinstance(value, str) else value.strip()
    if not text:
        return None
    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts):
        return None
    return ts


def entry_time_within_cutoff(entry: dict[str, Any], cutoff: pd.Timestamp | None) -> bool:
    if cutoff is None:
        return True
    ts = parse_datetime_text(entry.get("提交时间"))
    if ts is None:
        return True
    return ts <= cutoff


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_path_tokens(labels: list[str]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for label in labels:
        base = sanitize_filename_component(label) or "提交"
        grouped.setdefault(base, []).append(label)

    tokens: dict[str, str] = {}
    for base, label_list in grouped.items():
        if len(label_list) == 1:
            tokens[label_list[0]] = base
            continue
        for label in label_list:
            digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:8]
            tokens[label] = f"{base}-{digest}"
    return tokens


def discover_collection_excels(config_dir: Path) -> dict[str, Path]:
    courses: dict[str, Path] = {}
    for path in sorted(config_dir.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        parse_collection_title(path.stem)
        courses[path.stem] = path
    return courses


def require_column(df: pd.DataFrame, column: str, excel_path: Path) -> str:
    if column not in df.columns:
        raise ValueError(f"Excel 缺少列 `{column}`: {excel_path}")
    return column


def load_collection_excel(excel_path: Path) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    meta = parse_collection_title(excel_path.stem)
    df = pd.read_excel(excel_path)
    columns = {
        "name": require_column(df, "填写人", excel_path),
        "department": require_column(df, "所在部门", excel_path),
        "time": require_column(df, "填写时间", excel_path),
        "submission": require_column(df, "提交序号", excel_path),
        "content": require_column(df, "提交内容", excel_path),
        "file": require_column(df, "请上传对应文件", excel_path),
        "user_type": require_column(df, "用户类型", excel_path),
    }
    df = df.copy()
    df["_name_norm"] = df[columns["name"]].map(normalize_name)
    df["_submission_label"] = df[columns["submission"]].map(normalize_text)
    df["_content_label"] = df[columns["content"]].map(normalize_text)
    df["_uploaded_filename"] = df[columns["file"]].map(normalize_uploaded_filename)
    df["_record_time"] = pd.to_datetime(df[columns["time"]], errors="raise")

    blank_submission = df.index[df["_submission_label"] == ""].tolist()
    blank_content = df.index[df["_content_label"] == ""].tolist()
    if blank_submission:
        raise ValueError(f"提交序号不能为空: {excel_path}, 行号={blank_submission[:10]}")
    if blank_content:
        raise ValueError(f"提交内容不能为空: {excel_path}, 行号={blank_content[:10]}")

    for content in sorted(df["_content_label"].unique()):
        parse_submission_content(content)
    return df, meta, columns


def load_students_file(path: Path, label: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"找不到{label}: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{label}必须是 JSON 数组: {path}")
    return data


def load_students(
    students_json_path: Path,
    other_students_json_path: Path | None = None,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    students = load_students_file(students_json_path, "基础学生名单")
    by_class: dict[str, list[dict[str, str]]] = {}
    by_name: dict[str, dict[str, str]] = {}
    other_by_name: dict[str, dict[str, str]] = {}

    for item in students:
        class_name = str(item.get("班级", "")).strip()
        student_no = str(item.get("学号", "")).strip()
        raw_name = str(item.get("姓名", "")).strip()
        name_norm = normalize_name(raw_name)
        if not class_name or not student_no or not name_norm:
            continue
        student = {"班级": class_name, "学号": student_no, "姓名": raw_name, "姓名标准化": name_norm}
        if name_norm in by_name and by_name[name_norm]["学号"] != student_no:
            prev = by_name[name_norm]
            raise ValueError(f"基础学生名单存在重名冲突: {prev['学号']}{prev['姓名']} 与 {student_no}{raw_name}")
        by_class.setdefault(class_name, []).append(student)
        by_name[name_norm] = student

    if other_students_json_path and other_students_json_path.exists():
        for item in load_students_file(other_students_json_path, "其他学生名单"):
            student_no = str(item.get("学号", "")).strip()
            raw_name = str(item.get("姓名", "")).strip()
            name_norm = normalize_name(raw_name)
            if not student_no or not name_norm:
                continue
            student = {
                "班级": str(item.get("班级", "其他")).strip() or "其他",
                "学号": student_no,
                "姓名": raw_name,
                "姓名标准化": name_norm,
            }
            if name_norm in by_name and by_name[name_norm]["学号"] != student_no:
                prev = by_name[name_norm]
                raise ValueError(f"基础名单与其他名单重名冲突: {prev['学号']}{prev['姓名']} 与 {student_no}{raw_name}")
            other_by_name[name_norm] = student

    for students_in_class in by_class.values():
        students_in_class.sort(key=lambda item: item["学号"])
    return by_class, by_name, other_by_name


def expand_class_audience(audience: str) -> list[str]:
    classes: list[str] = []
    for token in audience.split("+"):
        text = token.strip()
        if not text:
            continue
        range_match = re.fullmatch(r"([A-Za-z])(\d{4})(\d{2})-(\d{2})", text)
        if range_match:
            prefix, grade, start_text, end_text = range_match.groups()
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise ValueError(f"班级范围无效: {text}")
            for number in range(start, end + 1):
                classes.append(f"{prefix.upper()}{grade}{number:02d}")
            continue
        if re.fullmatch(r"[A-Za-z]\d{6}", text):
            classes.append(text[0].upper() + text[1:])
            continue
    return sorted(dict.fromkeys(classes))


def detect_classes_from_excel(df: pd.DataFrame, students_by_name: dict[str, dict[str, str]]) -> list[str]:
    classes = {
        students_by_name[name_norm]["班级"]
        for name_norm in df["_name_norm"].tolist()
        if name_norm in students_by_name
    }
    return sorted(classes)


def resolve_target_classes(
    meta: dict[str, str],
    df: pd.DataFrame,
    students_by_name: dict[str, dict[str, str]],
) -> list[str]:
    audience_classes = expand_class_audience(meta["对象"])
    detected = detect_classes_from_excel(df, students_by_name)
    target = audience_classes or detected
    if not target:
        raise ValueError(f"无法从对象或 Excel 检测班级: {meta['课程']}")
    return target


def scope_students_by_classes(
    students_by_class: dict[str, list[dict[str, str]]],
    target_classes: list[str],
) -> dict[str, list[dict[str, str]]]:
    missing = [class_name for class_name in target_classes if class_name not in students_by_class]
    if missing:
        raise ValueError(f"学生名单缺少班级: {', '.join(missing)}")
    return {class_name: students_by_class[class_name] for class_name in target_classes}


def find_attachments_dir(course_name: str, attachments_root: Path, attachments_override: str) -> Path:
    if attachments_override.strip():
        path = Path(attachments_override).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"指定附件目录不存在: {path}")
        return path
    if not attachments_root.exists():
        raise FileNotFoundError(f"附件根目录不存在: {attachments_root}")
    candidates = [
        path
        for path in attachments_root.iterdir()
        if path.is_dir() and (course_name in path.name or path.name.startswith(course_name))
    ]
    preferred = [path for path in candidates if "收集的文件" in path.name]
    if len(preferred) == 1:
        return preferred[0].resolve()
    if len(preferred) > 1:
        raise ValueError("匹配到多个课程附件目录:\n" + "\n".join(str(path) for path in preferred))
    if len(candidates) == 1:
        return candidates[0].resolve()
    if len(candidates) > 1:
        raise ValueError("匹配到多个课程目录:\n" + "\n".join(str(path) for path in candidates))
    raise FileNotFoundError(f"未找到课程附件目录: {course_name}")


def build_attachment_lookup(attachments_dir: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    grouped: dict[str, list[str]] = {}
    for path in attachments_dir.iterdir():
        if not path.is_file():
            continue
        grouped.setdefault(normalize_filename_key(path.name), []).append(path.name)
    unique: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for key, names in grouped.items():
        if len(names) == 1:
            unique[key] = names[0]
        else:
            duplicates[key] = sorted(names)
    return unique, duplicates


def build_uploaded_refs(df: pd.DataFrame) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        filename = str(row["_uploaded_filename"]).strip()
        if not filename:
            continue
        key = normalize_filename_key(filename)
        refs.setdefault(key, set()).add(f"{row['_submission_label']}|{row['_content_label']}")
    return refs


def execute_source_attachment_cleanup(
    *,
    df: pd.DataFrame,
    selected_labels: list[str],
    attachments_dir: Path,
    attachment_lookup: dict[str, str],
    duplicate_lookup: dict[str, list[str]],
    course_out_dir: Path,
    mode: str,
) -> Path:
    if mode not in {"dry-run", "apply"}:
        raise ValueError(f"未知清理模式: {mode}")
    selected = set(selected_labels)
    uploaded_refs = build_uploaded_refs(df)
    df_selected = df[df["_submission_label"].isin(selected)]
    unique_keys = sorted({normalize_filename_key(name) for name in df_selected["_uploaded_filename"].tolist() if name})
    attachments_root = attachments_dir.resolve()
    planned: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    deleted: list[str] = []
    failures: list[dict[str, Any]] = []

    for key in unique_keys:
        outside_refs = sorted(
            ref
            for ref in uploaded_refs.get(key, set())
            if ref.split("|", 1)[0] not in selected
        )
        if outside_refs:
            protected.append({"附件键": key, "保护原因": "其他提交序号/提交内容仍引用", "引用": outside_refs})
            continue
        if key in duplicate_lookup:
            ambiguous.append({"附件键": key, "本地候选附件名": duplicate_lookup[key]})
            continue
        filename = attachment_lookup.get(key)
        if not filename:
            missing.append({"附件键": key, "原因": "本地同步目录未找到"})
            continue
        path = (attachments_dir / filename).resolve()
        try:
            path.relative_to(attachments_root)
        except ValueError:
            protected.append({"附件键": key, "本地附件名": filename, "保护原因": "目标不在附件目录内"})
            continue
        item = {"附件键": key, "本地附件名": filename, "本地绝对路径": str(path)}
        planned.append(item)
        if mode == "apply":
            try:
                if path.exists():
                    path.unlink()
                    deleted.append(filename)
                else:
                    failures.append({"本地附件名": filename, "原因": "执行删除时已不存在"})
            except OSError as err:
                failures.append({"本地附件名": filename, "原因": str(err)})

    report = {
        "模式": mode,
        "统计生成时间": now_text(),
        "附件目录": str(attachments_root),
        "选择提交序号": selected_labels,
        "汇总": {
            "计划删除附件数": len(planned),
            "实际删除附件数": len(deleted),
            "跨提交保护附件数": len(protected),
            "本地歧义附件数": len(ambiguous),
            "本地缺失附件数": len(missing),
            "删除失败附件数": len(failures),
        },
        "计划删除附件": planned,
        "实际删除附件": deleted,
        "跨提交保护附件": protected,
        "本地歧义附件": ambiguous,
        "本地缺失附件": missing,
        "删除失败附件": failures,
    }
    report_path = course_out_dir / "stats" / "source_attachment_cleanup.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(dump_json(report), encoding="utf-8")
    return report_path


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
        "课程": meta["课程"],
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
    if data.get("源附件缺失但保留归档"):
        version["源附件缺失但保留归档"] = True
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
        "课程": meta["课程"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
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
            "课程": meta["课程"],
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
                        version["源附件缺失但保留归档"] = True
                manifest["entries"][entry_id] = existing
            else:
                set_non_active_status(manifest, course_out_dir, entry_id, base_entry, "missing", "本地同步目录未找到附件")
            continue

        source_path = attachments_dir / source_filename
        if not source_path.exists():
            if isinstance(existing, dict) and has_active_archived_file(existing, course_out_dir):
                for version in existing.get("versions", []):
                    if active_version_file_exists(course_out_dir, version):
                        version["源附件缺失但保留归档"] = True
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


def load_existing_submission_cutoffs(web_data_root: Path, meta: dict[str, str]) -> dict[str, pd.Timestamp]:
    course_slug = sanitize_filename_component(meta["课程"])
    index_path = web_data_root / f"{course_slug}.index.json"
    if not index_path.exists():
        return {}
    index_data = read_json_object(index_path)
    cutoffs: dict[str, pd.Timestamp] = {}
    submission_refs = index_data.get("提交序号列表", [])
    if not isinstance(submission_refs, list):
        raise ValueError(f"收集表索引缺少提交序号列表: {index_path}")
    for item in submission_refs:
        if not isinstance(item, dict):
            continue
        label = str(item.get("提交序号", "")).strip()
        data_file = str(item.get("数据文件", "")).strip()
        if not label or not data_file:
            continue
        relative = data_file.removeprefix("data/").replace("/", "\\")
        stat_path = web_data_root / relative
        if not stat_path.exists():
            continue
        stat = read_json_object(stat_path)
        cutoff = parse_datetime_text(stat.get("统计截止时间") or stat.get("最后提交时间"))
        if cutoff is not None:
            cutoffs[label] = cutoff
    return cutoffs


def latest_record_time_by_label(df: pd.DataFrame, label: str) -> pd.Timestamp:
    selected = df[df["_submission_label"] == label]
    if selected.empty:
        raise ValueError(f"提交序号没有记录，无法确定截止时间: {label}")
    latest = selected["_record_time"].max()
    if pd.isna(latest):
        raise ValueError(f"提交序号填写时间无效，无法确定截止时间: {label}")
    return latest


def resolve_submission_cutoffs(
    *,
    df: pd.DataFrame,
    selected_labels: list[str],
    published_cutoffs: dict[str, pd.Timestamp],
    cutoff_policy: str,
    manual_cutoffs: dict[str, pd.Timestamp],
) -> dict[str, pd.Timestamp]:
    if cutoff_policy not in {"keep", "advance", "manual"}:
        raise ValueError(f"未知 cutoff policy: {cutoff_policy}")
    cutoffs: dict[str, pd.Timestamp] = {}
    for label in selected_labels:
        if cutoff_policy == "manual":
            cutoff = manual_cutoffs.get(label)
            if cutoff is None:
                raise ValueError(f"manual 模式缺少提交序号截止时间: {label}")
            cutoffs[label] = cutoff
            continue
        if label in manual_cutoffs:
            cutoffs[label] = manual_cutoffs[label]
            continue
        if cutoff_policy == "keep" and label in published_cutoffs:
            cutoffs[label] = published_cutoffs[label]
            continue
        cutoffs[label] = latest_record_time_by_label(df, label)
    return cutoffs


def build_missing_attachment_summary(stat: dict[str, Any]) -> dict[str, Any]:
    by_class: dict[str, list[str]] = {}
    for class_name, class_stat in stat.get("班级统计", {}).items():
        missing = sorted(set(class_stat.get("已交但附件缺失名单", [])))
        if missing:
            by_class[class_name] = missing
    other = sorted(set(stat.get("其他已交但附件缺失名单", [])))
    if other:
        by_class["其他"] = other
    total = sum(len(items) for items in by_class.values())
    summary: dict[str, Any] = {"总人数": total, "班级统计": by_class}
    if total:
        summary["同步提示"] = "检测到表格有提交记录但本地未找到附件，若归档中已有文件则不会回退。"
    return summary


def build_invalid_attachment_summary(stat: dict[str, Any]) -> dict[str, Any]:
    by_class: dict[str, list[str]] = {}
    for class_name, class_stat in stat.get("班级统计", {}).items():
        invalid = sorted(set(class_stat.get("无效附件名单", [])))
        if invalid:
            by_class[class_name] = invalid
    other = sorted(set(stat.get("其他无效附件名单", [])))
    if other:
        by_class["其他"] = other
    total = sum(len(items) for items in by_class.values())
    return {"总人数": total, "班级统计": by_class}


def make_submission_stat(
    *,
    df: pd.DataFrame,
    columns: dict[str, str],
    meta: dict[str, str],
    manifest: dict[str, Any],
    submission_label: str,
    content_labels: list[str],
    students_by_class: dict[str, list[dict[str, str]]],
    other_students_by_name: dict[str, dict[str, str]],
    cutoff: pd.Timestamp | None,
) -> dict[str, Any]:
    df_submission = df[df["_submission_label"] == submission_label]
    if cutoff is not None:
        df_submission = df_submission[df_submission["_record_time"] <= cutoff]
    latest_record_time = format_datetime(df_submission["_record_time"].max()) if not df_submission.empty else ""

    content_stats: dict[str, Any] = {}
    stat: dict[str, Any] = {
        "课程": meta["课程"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "状态": "active",
        "提交序号": submission_label,
        "提交内容列表": content_labels,
        "最后提交时间": "",
        "统计截止时间": format_datetime(cutoff) if cutoff is not None else "",
        "最后收集记录时间": latest_record_time,
        "统计生成时间": now_text(),
        "总班级数": len(students_by_class),
        "班级统计": {},
        "补交状态": {},
    }

    valid_submit_times: list[pd.Timestamp] = []
    total_expected = 0
    total_submitted = 0
    total_missing = 0
    total_invalid = 0

    for content_label in content_labels:
        content_stats[content_label] = {"班级统计": {}}

    for class_name, students in students_by_class.items():
        complete_students: list[str] = []
        not_complete_students: list[str] = []
        class_missing_students: set[str] = set()
        class_invalid_students: set[str] = set()
        class_late_complete_students: set[str] = set()
        class_late_missing_students: set[str] = set()
        class_late_invalid_students: set[str] = set()

        for content_label in content_labels:
            content_submitted: list[str] = []
            content_not_submitted: list[str] = []
            content_missing: list[str] = []
            content_invalid: list[str] = []
            content_late_submitted: list[str] = []
            content_late_missing: list[str] = []
            content_late_invalid: list[str] = []
            for student in students:
                entry = active_entry_for(manifest, student["学号"], submission_label, content_label, cutoff)
                if entry and entry.get("状态") == "active":
                    content_submitted.append(student["学号"])
                    ts = parse_datetime_text(entry.get("提交时间"))
                    if ts is not None:
                        valid_submit_times.append(ts)
                else:
                    content_not_submitted.append(student["学号"])
                    if entry and entry.get("状态") == "missing":
                        content_missing.append(student["学号"])
                        class_missing_students.add(student["学号"])
                    if entry and entry.get("状态") == "invalid":
                        content_invalid.append(student["学号"])
                        class_invalid_students.add(student["学号"])
                    late_entry = latest_version_after_cutoff(manifest, student["学号"], submission_label, content_label, cutoff)
                    if late_entry and late_entry.get("状态") == "active":
                        content_late_submitted.append(student["学号"])
                    elif late_entry and late_entry.get("状态") == "missing":
                        content_late_missing.append(student["学号"])
                    elif late_entry and late_entry.get("状态") == "invalid":
                        content_late_invalid.append(student["学号"])
            content_stats[content_label]["班级统计"][class_name] = {
                "应交人数": len(students),
                "已交人数": len(content_submitted),
                "未交人数": len(content_not_submitted),
                "提交率": round((len(content_submitted) / len(students)) if students else 0, 4),
                "已交名单": sorted(content_submitted),
                "未交名单": sorted(content_not_submitted),
                "已交但附件缺失人数": len(content_missing),
                "已交但附件缺失名单": sorted(content_missing),
                "无效附件人数": len(content_invalid),
                "无效附件名单": sorted(content_invalid),
                "已补交人数": len(content_late_submitted),
                "已补交名单": sorted(content_late_submitted),
                "补交附件缺失人数": len(content_late_missing),
                "补交附件缺失名单": sorted(content_late_missing),
                "补交无效人数": len(content_late_invalid),
                "补交无效名单": sorted(content_late_invalid),
            }

        for student in students:
            entries = [
                active_entry_for(manifest, student["学号"], submission_label, content_label, cutoff)
                for content_label in content_labels
            ]
            if entries and all(entry and entry.get("状态") == "active" for entry in entries):
                complete_students.append(student["学号"])
            else:
                not_complete_students.append(student["学号"])
                late_entries = [
                    latest_version_after_cutoff(manifest, student["学号"], submission_label, content_label, cutoff)
                    for content_label in content_labels
                ]
                if late_entries and all(entry and entry.get("状态") == "active" for entry in late_entries):
                    class_late_complete_students.add(student["学号"])
                elif any(entry and entry.get("状态") == "invalid" for entry in late_entries):
                    class_late_invalid_students.add(student["学号"])
                elif any(entry and entry.get("状态") == "missing" for entry in late_entries):
                    class_late_missing_students.add(student["学号"])

        expected_count = len(students)
        submitted_count = len(complete_students)
        total_expected += expected_count
        total_submitted += submitted_count
        total_missing += len(class_missing_students)
        total_invalid += len(class_invalid_students)
        stat["班级统计"][class_name] = {
            "应交人数": expected_count,
            "已交人数": submitted_count,
            "未交人数": expected_count - submitted_count,
            "提交率": round((submitted_count / expected_count) if expected_count else 0, 4),
            "已交名单": sorted(complete_students),
            "未交名单": sorted(not_complete_students),
            "已交但附件缺失人数": len(class_missing_students),
            "已交但附件缺失名单": sorted(class_missing_students),
            "无效附件人数": len(class_invalid_students),
            "无效附件名单": sorted(class_invalid_students),
            "已补交人数": len(class_late_complete_students),
            "已补交名单": sorted(class_late_complete_students),
            "补交附件缺失人数": len(class_late_missing_students),
            "补交附件缺失名单": sorted(class_late_missing_students),
            "补交无效人数": len(class_late_invalid_students),
            "补交无效名单": sorted(class_late_invalid_students),
        }
        stat["补交状态"][class_name] = {
            "已补交名单": sorted(class_late_complete_students),
            "补交无效名单": sorted(class_late_invalid_students),
            "补交附件缺失名单": sorted(class_late_missing_students),
        }

    other_submitted: list[str] = []
    other_missing: set[str] = set()
    other_invalid: set[str] = set()
    for student in other_students_by_name.values():
        entries = [
            active_entry_for(manifest, student["学号"], submission_label, content_label, cutoff)
            for content_label in content_labels
        ]
        if entries and all(entry and entry.get("状态") == "active" for entry in entries):
            other_submitted.append(student["学号"])
            for entry in entries:
                ts = parse_datetime_text(entry.get("提交时间")) if entry else None
                if ts is not None:
                    valid_submit_times.append(ts)
        else:
            for entry in entries:
                if not entry:
                    continue
                if entry.get("状态") == "missing":
                    other_missing.add(student["学号"])
                if entry.get("状态") == "invalid":
                    other_invalid.add(student["学号"])

    if valid_submit_times:
        stat["最后提交时间"] = format_datetime(max(valid_submit_times))
    stat["其他已交名单"] = sorted(other_submitted)
    stat["其他已交但附件缺失名单"] = sorted(other_missing)
    stat["其他无效附件名单"] = sorted(other_invalid)
    stat["汇总"] = {
        "应交总人数": total_expected,
        "已交总人数": total_submitted,
        "未交总人数": total_expected - total_submitted,
        "总提交率": round((total_submitted / total_expected) if total_expected else 0, 4),
        "已交但附件缺失总人数": total_missing + len(other_missing),
        "无效附件总人数": total_invalid + len(other_invalid),
    }
    stat["提交内容统计"] = content_stats
    stat["附件缺失"] = build_missing_attachment_summary(stat)
    stat["无效附件"] = build_invalid_attachment_summary(stat)
    return stat


def active_entries_for_submission(
    manifest: dict[str, Any],
    submission_label: str,
    cutoff: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    entries = []
    for entry in manifest.get("entries", {}).values():
        if not isinstance(entry, dict) or entry.get("提交序号") != submission_label:
            continue
        versions = [
            version
            for version in entry.get("versions", [])
            if isinstance(version, dict)
            and version.get("状态") == "active"
            and entry_time_within_cutoff(version, cutoff)
        ]
        if versions:
            entries.append(merged_entry_version(entry, sorted(versions, key=version_sort_key)[-1]))
    return sorted(entries, key=lambda item: (str(item.get("提交内容名", "")), str(item.get("班级", "")), str(item.get("学号", ""))))


def create_submission_zip(
    course_out_dir: Path,
    submission_label: str,
    manifest: dict[str, Any],
    cutoff: pd.Timestamp | None = None,
) -> Path:
    zip_dir = course_out_dir / "zip"
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / f"{sanitize_filename_component(submission_label)}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in active_entries_for_submission(manifest, submission_label, cutoff):
            rel = str(entry.get("文件相对路径", "")).strip()
            if not rel:
                continue
            source = course_out_dir / rel
            if not source.exists():
                continue
            arcname = "/".join(
                [
                    sanitize_filename_component(str(entry.get("提交内容名", ""))),
                    sanitize_filename_component(str(entry.get("班级", ""))),
                    source.name,
                ]
            )
            zf.write(source, arcname)
    return zip_path


def write_submission_reports(
    course_out_dir: Path,
    submission_label: str,
    stat: dict[str, Any],
) -> None:
    stats_dir = course_out_dir / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    token = sanitize_filename_component(submission_label)
    (stats_dir / f"{token}.json").write_text(dump_json(stat), encoding="utf-8")
    missing = stat.get("附件缺失", {})
    invalid = stat.get("无效附件", {})
    if int(missing.get("总人数", 0) or 0) > 0:
        (stats_dir / f"{token}.missing_attachments.json").write_text(dump_json(missing), encoding="utf-8")
    if int(invalid.get("总人数", 0) or 0) > 0:
        (stats_dir / f"{token}.invalid_attachments.json").write_text(dump_json(invalid), encoding="utf-8")


def read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 必须是对象: {path}")
    return data


def rebuild_course_index_from_data(web_data_root: Path, course_index_path: Path) -> None:
    course_items: list[dict[str, Any]] = []
    for index_file in sorted(web_data_root.glob("*.index.json")):
        data = read_json_object(index_file)
        course_name = str(data.get("课程", "")).strip()
        if not course_name:
            continue
        course_items.append(
            {
                "课程": course_name,
                "数据文件": f"data/{index_file.name}",
                "主题": str(data.get("主题", course_name)).strip(),
                "对象": str(data.get("对象", "")).strip(),
                "周期": str(data.get("周期", "")).strip(),
                "状态": str(data.get("状态", "active")).strip() or "active",
            }
        )
    course_items.sort(key=lambda item: (item.get("周期") or "未分组", item["状态"] == "archived", item["课程"]))
    course_index_path.parent.mkdir(parents=True, exist_ok=True)
    course_index_path.write_text(
        dump_json({"更新时间": now_text(), "课程列表": course_items}),
        encoding="utf-8",
    )


def write_collection_web_data(
    *,
    web_data_root: Path,
    course_index_path: Path,
    meta: dict[str, str],
    submission_stats: dict[str, dict[str, Any]],
    ordered_labels: list[str],
) -> None:
    web_data_root.mkdir(parents=True, exist_ok=True)
    course_slug = sanitize_filename_component(meta["课程"])
    tokens = build_path_tokens(ordered_labels)
    keep_files: set[str] = set()
    submission_refs: list[dict[str, Any]] = []

    for label in ordered_labels:
        stat = submission_stats.get(label)
        if stat is None:
            continue
        token = tokens[label]
        filename = f"{course_slug}.{token}.json"
        keep_files.add(filename)
        payload = dict(stat)
        payload["更新时间"] = now_text()
        (web_data_root / filename).write_text(dump_json(payload), encoding="utf-8")
        submission_refs.append(
            {
                "提交序号": label,
                "数据文件": f"data/{filename}",
                "提交内容列表": stat.get("提交内容列表", []),
            }
        )

    index_filename = f"{course_slug}.index.json"
    keep_files.add(index_filename)
    index_payload = {
        "课程": meta["课程"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "状态": "active",
        "更新时间": now_text(),
        "提交序号列表": submission_refs,
    }
    (web_data_root / index_filename).write_text(dump_json(index_payload), encoding="utf-8")

    for stale in web_data_root.glob(f"{course_slug}.*.json"):
        if stale.name not in keep_files:
            stale.unlink()

    rebuild_course_index_from_data(web_data_root, course_index_path)
    rebuild_course_manifest(public_root=course_index_path.parent, course_index_path=course_index_path)


def process_collection(
    *,
    excel_path: Path,
    cfg: dict[str, Any],
    repo_root: Path,
    requested_labels: list[str],
    attachments_override: str,
    cutoff_policy: str,
    manual_cutoffs: dict[str, pd.Timestamp],
    cleanup_mode: str,
    cleanup_only: bool,
) -> dict[str, Any]:
    df, meta, columns = load_collection_excel(excel_path)
    all_labels = sorted(dict.fromkeys(df["_submission_label"].tolist()), key=sort_submission_key)
    if not requested_labels:
        raise ValueError("必须通过 --label 或 --all-labels 显式选择提交序号。")
    selected_labels = all_labels if requested_labels == ["__ALL__"] else requested_labels
    unknown = [label for label in selected_labels if label not in all_labels]
    if unknown:
        raise ValueError(f"提交序号不存在: {', '.join(unknown)}")

    students_path = resolve_path(cfg.get("students", "config/B240401_to_B240403_students.json"), repo_root)
    other_text = str(cfg.get("other_students", "")).strip()
    other_path = resolve_path(other_text, repo_root) if other_text else Path()
    students_by_class_all, students_by_name, other_students_by_name = load_students(
        students_json_path=students_path,
        other_students_json_path=other_path if other_text else None,
    )
    target_classes = resolve_target_classes(meta, df, students_by_name)
    students_by_class = scope_students_by_classes(students_by_class_all, target_classes)

    attachments_root = resolve_path(cfg.get("attachments_root", ""), repo_root)
    attachments_dir = find_attachments_dir(meta["课程"], attachments_root, attachments_override)
    attachment_lookup, duplicate_lookup = build_attachment_lookup(attachments_dir)

    out_root = resolve_path(cfg.get("out_root", "out"), repo_root)
    web_data_root = resolve_path(cfg.get("web_data_root", "webapp/public/data"), repo_root)
    course_index_path = resolve_path(cfg.get("course_index", "webapp/public/courses.json"), repo_root)
    course_out_dir = out_root / meta["课程"]
    course_out_dir.mkdir(parents=True, exist_ok=True)
    published_cutoffs = load_existing_submission_cutoffs(web_data_root, meta)
    submission_cutoffs = resolve_submission_cutoffs(
        df=df,
        selected_labels=selected_labels,
        published_cutoffs=published_cutoffs,
        cutoff_policy=cutoff_policy,
        manual_cutoffs=manual_cutoffs,
    )

    if cleanup_only:
        if cleanup_mode == "off":
            raise ValueError("--cleanup-only 必须搭配 --cleanup-source-attachments dry-run/apply")
        report_path = execute_source_attachment_cleanup(
            df=df,
            selected_labels=selected_labels,
            attachments_dir=attachments_dir,
            attachment_lookup=attachment_lookup,
            duplicate_lookup=duplicate_lookup,
            course_out_dir=course_out_dir,
            mode=cleanup_mode,
        )
        return {"课程": meta["课程"], "清理报告": str(report_path)}

    manifest = merge_incremental_archive(
        df=df,
        columns=columns,
        meta=meta,
        selected_labels=selected_labels,
        course_out_dir=course_out_dir,
        attachments_dir=attachments_dir,
        attachment_lookup=attachment_lookup,
        duplicate_lookup=duplicate_lookup,
        students_by_name=students_by_name,
        other_students_by_name=other_students_by_name,
    )

    stats: dict[str, dict[str, Any]] = {}
    zip_paths: list[str] = []
    for label in selected_labels:
        label_rows = df[df["_submission_label"] == label]
        cutoff = submission_cutoffs.get(label)
        if cutoff is not None:
            label_rows = label_rows[label_rows["_record_time"] <= cutoff]
        content_labels = sorted(dict.fromkeys(label_rows["_content_label"].tolist()))
        if not content_labels:
            content_labels = sorted(dict.fromkeys(df[df["_submission_label"] == label]["_content_label"].tolist()))
        stat = make_submission_stat(
            df=df,
            columns=columns,
            meta=meta,
            manifest=manifest,
            submission_label=label,
            content_labels=content_labels,
            students_by_class=students_by_class,
            other_students_by_name=other_students_by_name,
            cutoff=cutoff,
        )
        stats[label] = stat
        write_submission_reports(course_out_dir, label, stat)
        zip_paths.append(str(create_submission_zip(course_out_dir, label, manifest, cutoff)))

    summary = {
        "课程": meta["课程"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "更新时间": now_text(),
        "提交序号列表": selected_labels,
        "统计文件目录": str(course_out_dir / "stats"),
        "压缩包列表": zip_paths,
    }
    (course_out_dir / "collection_summary.json").write_text(dump_json(summary), encoding="utf-8")

    if cleanup_mode != "off":
        summary["源附件清理报告"] = str(
            execute_source_attachment_cleanup(
                df=df,
                selected_labels=selected_labels,
                attachments_dir=attachments_dir,
                attachment_lookup=attachment_lookup,
                duplicate_lookup=duplicate_lookup,
                course_out_dir=course_out_dir,
                mode=cleanup_mode,
            )
        )
        (course_out_dir / "collection_summary.json").write_text(dump_json(summary), encoding="utf-8")

    write_collection_web_data(
        web_data_root=web_data_root,
        course_index_path=course_index_path,
        meta=meta,
        submission_stats=stats,
        ordered_labels=selected_labels,
    )
    return summary


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    parser = argparse.ArgumentParser(description="新模型增量收集: 主题[对象][周期] + 提交序号 + 提交内容 + 文件")
    parser.add_argument("--config", default=str(repo_root / "config" / "local.config.json"))
    parser.add_argument("--excel", default="", help="指定新模型 Excel")
    parser.add_argument("--course", default="", help="按标题精确选择 config 下的 Excel")
    parser.add_argument("--attachments", default="", help="覆盖附件同步目录")
    parser.add_argument("--label", action="append", dest="labels", default=[], help="要处理的提交序号，可多次指定")
    parser.add_argument("--all-labels", action="store_true", help="显式处理当前 Excel 的全部提交序号")
    parser.add_argument(
        "--cutoff-policy",
        choices=["keep", "advance", "manual"],
        default="keep",
        help="统计截止时间策略：keep 保留已发布截止，新提交序号用最新记录；advance 推进到最新记录；manual 使用 --cutoff",
    )
    parser.add_argument(
        "--cutoff",
        action="append",
        default=[],
        help="manual 截止时间，格式：提交序号=YYYY-MM-DD HH:MM:SS，可重复",
    )
    parser.add_argument(
        "--cleanup-source-attachments",
        choices=["off", "dry-run", "apply"],
        default="off",
        help="按选中提交序号清理企业微信同步源附件，默认不清理",
    )
    parser.add_argument("--cleanup-only", action="store_true", help="仅执行源附件清理，不更新归档和 web 数据")
    parser.add_argument("--list-courses", action="store_true")
    parser.add_argument("--list-submission-labels", action="store_true")
    return parser.parse_args()


def parse_manual_cutoffs(values: list[str]) -> dict[str, pd.Timestamp]:
    cutoffs: dict[str, pd.Timestamp] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--cutoff 必须符合 提交序号=YYYY-MM-DD HH:MM:SS: {value}")
        label, raw_time = value.split("=", 1)
        label = normalize_text(label)
        cutoff = parse_datetime_text(raw_time)
        if not label or cutoff is None:
            raise ValueError(f"--cutoff 无效: {value}")
        cutoffs[label] = cutoff
    return cutoffs


def pick_excel(args: argparse.Namespace, repo_root: Path, cfg: dict[str, Any]) -> tuple[str, Path]:
    config_dir = resolve_path(cfg.get("courses_dir", "config"), repo_root)
    courses = discover_collection_excels(config_dir)
    if args.list_courses:
        for name, path in courses.items():
            print(f"{name}\t{path}")
        raise SystemExit(0)
    if args.excel:
        path = Path(args.excel).expanduser()
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Excel 不存在: {path}")
        parse_collection_title(path.stem)
        return path.stem, path
    if args.course:
        if args.course not in courses:
            raise ValueError(f"课程不存在或不是新模型标题: {args.course}")
        return args.course, courses[args.course]
    if len(courses) == 1:
        name = next(iter(courses))
        return name, courses[name]
    raise ValueError("检测到多份新模型 Excel，请使用 --course 或 --excel 指定。")


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    args = parse_args()
    cfg = load_local_config(resolve_path(args.config, repo_root))
    course_name, excel_path = pick_excel(args, repo_root, cfg)
    df, _, _ = load_collection_excel(excel_path)
    labels = sorted(dict.fromkeys(df["_submission_label"].tolist()), key=sort_submission_key)
    if args.list_submission_labels:
        print(f">>> {course_name}")
        for idx, label in enumerate(labels, 1):
            contents = sorted(dict.fromkeys(df[df["_submission_label"] == label]["_content_label"].tolist()))
            print(f"{idx}. {label} | {', '.join(contents)}")
        return

    requested_labels = ["__ALL__"] if args.all_labels else [normalize_text(label) for label in args.labels]
    summary = process_collection(
        excel_path=excel_path,
        cfg=cfg,
        repo_root=repo_root,
        requested_labels=requested_labels,
        attachments_override=args.attachments,
        cutoff_policy=args.cutoff_policy,
        manual_cutoffs=parse_manual_cutoffs(args.cutoff),
        cleanup_mode=args.cleanup_source_attachments,
        cleanup_only=args.cleanup_only,
    )
    print("处理完成:")
    print(dump_json(summary))


if __name__ == "__main__":
    main()
