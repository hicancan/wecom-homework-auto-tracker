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
TOPIC_SLUG_REPLACEMENTS = (
    ("人工智能导论及其Python应用实践实验", "ai-python-exp"),
    ("算法分析与设计作业", "algorithm-design-homework"),
    ("算法分析与设计实验", "algorithm-design-exp"),
    ("数学建模期末大作业", "math-modeling-final"),
    ("认识实习", "internship"),
    ("人工智能", "ai"),
    ("算法分析与设计", "algorithm-design"),
    ("数学建模", "math-modeling"),
    ("期末大作业", "final"),
    ("大作业", "project"),
    ("实验报告", "lab-report"),
    ("实验", "exp"),
    ("作业", "homework"),
    ("报告", "report"),
    ("实习", "internship"),
)
PERIOD_SLUGS = {
    "大一上": "freshman-fall",
    "大一下": "freshman-spring",
    "大二上": "sophomore-fall",
    "大二下": "sophomore-spring",
    "大三上": "junior-fall",
    "大三下": "junior-spring",
    "大四上": "senior-fall",
    "大四下": "senior-spring",
}


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


def slugify_ascii(text: str) -> str:
    raw = str(text or "")
    for source, replacement in TOPIC_SLUG_REPLACEMENTS:
        raw = raw.replace(source, f" {replacement} ")
    raw = raw.replace("&", " and ")
    tokens = re.findall(r"[A-Za-z0-9]+", raw)
    return "-".join(token.lower() for token in tokens)


def slugify_topic(topic: str) -> str:
    slug = slugify_ascii(topic)
    if slug:
        return slug
    digest = hashlib.sha1(topic.encode("utf-8")).hexdigest()[:8]
    return f"collection-{digest}"


def slugify_audience(audience: str) -> str:
    slug = slugify_ascii(audience)
    if slug:
        return slug
    digest = hashlib.sha1(audience.encode("utf-8")).hexdigest()[:8]
    return f"audience-{digest}"


def slugify_period(period: str) -> str:
    text = str(period or "").strip()
    if not text:
        return ""
    if text in PERIOD_SLUGS:
        return PERIOD_SLUGS[text]
    slug = slugify_ascii(text)
    if slug:
        return slug
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"period-{digest}"


def suggest_collection_id(title: str, existing_ids: set[str] | None = None) -> str:
    meta = parse_collection_title(title)
    parts = [
        slugify_topic(meta["主题"]),
        slugify_audience(meta["对象"]),
        slugify_period(meta["周期"]),
    ]
    base = require_collection_id("-".join(part for part in parts if part))
    used = existing_ids or set()
    if base not in used:
        return base
    suffix = 2
    while f"{base}-{suffix}" in used:
        suffix += 1
    return f"{base}-{suffix}"


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
    if " 24:" in text:
        text = text.replace(" 24:", " 00:")
        ts = pd.to_datetime(text, errors="coerce")
        return ts + pd.Timedelta(days=1) if not pd.isna(ts) else None
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


def entry_time_in_publication_window(
    entry: dict[str, Any],
    cutoff: pd.Timestamp | None,
    makeup_window_start: pd.Timestamp | None,
    makeup_window_end: pd.Timestamp | None,
) -> bool:
    if makeup_window_end is None:
        return entry_time_within_cutoff(entry, cutoff)

    ts = parse_datetime_text(entry.get("提交时间"))
    if ts is None:
        return False

    if cutoff is not None and ts <= cutoff:
        return True

    start = makeup_window_start or cutoff
    if start is not None and ts <= start:
        return False
    return ts <= makeup_window_end


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
