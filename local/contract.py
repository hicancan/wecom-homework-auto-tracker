from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


TITLE_RE = re.compile(r"^(?P<topic>[^\[\]]+)\[(?P<audience>[^\[\]]+)\](?:\[(?P<period>[^\[\]]+)\])?$")
CONTENT_RE = re.compile(r"^(?P<name>.+?)\((?P<exts>\.[A-Za-z0-9]+(?:/\.[A-Za-z0-9]+)*)\)$")
COLLECTION_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
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
        "标题": title.strip(),
        "主题": topic,
        "对象": audience,
        "周期": period,
    }


def require_collection_id(value: str) -> str:
    text = str(value or "").strip()
    if not COLLECTION_ID_RE.fullmatch(text):
        raise ValueError(f"collection_id 必须是小写 ASCII 短横线 ID: {value}")
    return text


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
        number = extract_submission_number(label)
        base = f"seq-{number:03d}" if number is not None else (sanitize_filename_component(label) or "seq")
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
