# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pandas",
#     "openpyxl",
# ]
# ///
import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from course_manifest import rebuild_course_manifest

DEFAULT_ALLOWED_SUBMISSION_EXTENSIONS = (".doc", ".docx", ".pdf")
ALLOW_ALL_EXTENSIONS = object()


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


def save_local_config(config_path: Path, cfg: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def pick_setting(cli_value: str, cfg: dict[str, Any], key: str, fallback: str = "") -> str:
    if str(cli_value).strip():
        return str(cli_value).strip()
    cfg_value = cfg.get(key)
    if cfg_value is None:
        return fallback
    return str(cfg_value).strip() or fallback


def resolve_path(text: str, base_dir: Path) -> Path:
    raw = str(text).strip()
    if not raw:
        return Path()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name)).strip()


def sanitize_filename_component(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(text)).strip()


def extract_homework_number(hw_name: str) -> int | None:
    match = re.search(r"(\d+)", str(hw_name))
    return int(match.group(1)) if match else None


def parse_homework_order(hw_name: str) -> int:
    order = extract_homework_number(hw_name)
    return order if order is not None else 10**9


def parse_bool_setting(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def normalize_extension(value: Any) -> str:
    raw = str(value).strip().lower()
    if not raw:
        return ""
    if raw == "*":
        return "*"
    return raw if raw.startswith(".") else f".{raw}"


def parse_extension_allowlist(value: Any) -> tuple[str, ...] | object | None:
    if value is None:
        return None

    items: list[Any]
    if isinstance(value, str):
        items = re.split(r"[\s,;|]+", value.strip())
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]

    normalized: list[str] = []
    for item in items:
        ext = normalize_extension(item)
        if not ext:
            continue
        if ext == "*":
            return ALLOW_ALL_EXTENSIONS
        normalized.append(ext)

    if not normalized:
        return None
    return tuple(sorted(set(normalized)))


def resolve_course_extension_allowlist(
    cfg: dict[str, Any],
    map_key: str,
    course_name: str,
    default: tuple[str, ...],
) -> tuple[str, ...] | None:
    raw = cfg.get(map_key)
    selected: Any = raw
    if isinstance(raw, dict):
        selected = raw.get(course_name)
        if selected is None or selected == "" or selected == []:
            selected = raw.get("default")

    parsed = parse_extension_allowlist(selected)
    if parsed is ALLOW_ALL_EXTENSIONS:
        return None
    if isinstance(parsed, tuple):
        return parsed

    fallback = parse_extension_allowlist(default)
    if fallback is ALLOW_ALL_EXTENSIONS:
        return None
    if isinstance(fallback, tuple):
        return fallback
    raise ValueError("有效提交后缀配置无效，且默认后缀白名单不可用。")


def is_allowed_attachment_filename(
    filename: str,
    allowed_extensions: tuple[str, ...] | None,
) -> bool:
    if allowed_extensions is None:
        return True
    ext = normalize_extension(Path(str(filename).strip()).suffix)
    return ext in allowed_extensions


def format_allowed_extensions(allowed_extensions: tuple[str, ...] | None) -> str:
    if allowed_extensions is None:
        return "全部允许"
    return ", ".join(allowed_extensions)


def resolve_course_template(
    cfg: dict[str, Any],
    map_key: str,
    course_name: str,
    default: str,
) -> str:
    raw = cfg.get(map_key)
    if isinstance(raw, dict):
        course_template = str(raw.get(course_name, "")).strip()
        if course_template:
            return course_template
        default_template = str(raw.get("default", "")).strip()
        if default_template:
            return default_template
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return default


def render_template_text(template: str, context: dict[str, Any], label: str) -> str:
    try:
        rendered = template.format_map(context)
    except KeyError as err:
        missing = str(err).strip("'")
        raise ValueError(f"{label}模板包含未知字段: {missing}") from err
    return str(rendered).strip()


def build_output_filename(
    template: str,
    *,
    student_no: str,
    student_name: str,
    class_name: str,
    course_name: str,
    homework_label: str,
    homework_order: int,
    ext: str,
) -> str:
    numeric_order = extract_homework_number(homework_label)
    context = {
        "student_no": sanitize_filename_component(student_no),
        "student_name": sanitize_filename_component(student_name),
        "class_name": sanitize_filename_component(class_name),
        "course_name": sanitize_filename_component(course_name),
        "homework_label": sanitize_filename_component(homework_label),
        "homework_order": (numeric_order if numeric_order is not None else 0),
        "report_title": (
            f"实验报告{numeric_order}" if numeric_order is not None else sanitize_filename_component(homework_label)
        ),
        "ext": ext,
    }
    rendered = render_template_text(template, context, "输出文件名")
    filename = sanitize_filename_component(rendered)
    if not filename:
        raise ValueError("输出文件名模板渲染后为空。")
    if ext and not filename.lower().endswith(ext.lower()):
        filename = f"{filename}{ext}"
    return filename


def build_zip_filename(
    template: str,
    *,
    course_name: str,
    homework_label: str,
    homework_order: int,
) -> str:
    numeric_order = extract_homework_number(homework_label)
    context = {
        "course_name": sanitize_filename_component(course_name),
        "homework_label": sanitize_filename_component(homework_label),
        "homework_order": (numeric_order if numeric_order is not None else 0),
    }
    rendered = render_template_text(template, context, "压缩包名")
    filename = sanitize_filename_component(rendered)
    if not filename:
        raise ValueError("压缩包名模板渲染后为空。")
    if not filename.lower().endswith(".zip"):
        filename = f"{filename}.zip"
    return filename


def create_homework_zip(
    homework_output_dir: Path,
    zip_dir: Path,
    zip_filename: str,
) -> Path:
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / zip_filename
    if zip_path.exists():
        zip_path.unlink()

    archive_path = shutil.make_archive(
        base_name=str(zip_path.with_suffix("")),
        format="zip",
        root_dir=str(homework_output_dir.parent),
        base_dir=homework_output_dir.name,
    )
    return Path(archive_path)


def normalize_homework_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def discover_homework_labels(df: pd.DataFrame) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for raw in df["_homework_label"].tolist():
        label = str(raw).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def build_homework_path_tokens(labels: list[str]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for label in labels:
        base = sanitize_filename_component(label) or "作业"
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


def normalize_uploaded_filename(value: Any) -> str:
    raw = str(value).strip()
    if not raw:
        return ""
    cleaned = raw.replace("\\", "/")
    if "/" in cleaned:
        cleaned = cleaned.split("/")[-1]
    return cleaned.strip()


def normalize_filename_key(filename: str) -> str:
    return str(filename).strip().lower()


def build_attachment_lookup(
    attachments_dir: Path,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    grouped: dict[str, list[str]] = {}
    for path in attachments_dir.iterdir():
        if not path.is_file():
            continue
        key = normalize_filename_key(path.name)
        grouped.setdefault(key, []).append(path.name)

    unique_lookup: dict[str, str] = {}
    duplicate_lookup: dict[str, list[str]] = {}
    for key, names in grouped.items():
        if len(names) == 1:
            unique_lookup[key] = names[0]
        else:
            duplicate_lookup[key] = sorted(names)
    return unique_lookup, duplicate_lookup


def discover_courses(config_dir: Path) -> dict[str, Path]:
    courses: dict[str, Path] = {}
    for path in sorted(config_dir.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        courses[path.stem] = path
    return courses


def choose_course_excel(courses: dict[str, Path], course_arg: str, excel_arg: str) -> tuple[str, Path]:
    if excel_arg:
        excel_path = Path(excel_arg).expanduser().resolve()
        if not excel_path.exists():
            raise FileNotFoundError(f"找不到Excel文件: {excel_path}")
        course_name = course_arg.strip() if course_arg.strip() else excel_path.stem
        return course_name, excel_path

    if not courses:
        raise FileNotFoundError("config 目录下未发现可用课程 Excel。")

    if course_arg.strip():
        course_text = course_arg.strip()
        if course_text in courses:
            return course_text, courses[course_text]

        partial = [name for name in courses if course_text in name]
        if len(partial) == 1:
            picked = partial[0]
            return picked, courses[picked]
        if len(partial) > 1:
            joined = "\n".join(f"- {name}" for name in partial)
            raise ValueError(f"课程名匹配到多个 Excel，请更精确输入:\n{joined}")
        raise ValueError(f"未找到课程 '{course_text}' 对应的 Excel。")

    if len(courses) == 1:
        only_name = next(iter(courses))
        return only_name, courses[only_name]

    joined = "\n".join(f"- {name}" for name in courses)
    raise ValueError(f"检测到多门课程，请使用 --course 指定:\n{joined}")


def find_attachments_dir(course_name: str, attachments_root: Path, attachments_dir: str) -> Path:
    if attachments_dir.strip():
        picked = Path(attachments_dir).expanduser().resolve()
        if not picked.exists():
            raise FileNotFoundError(f"指定的附件目录不存在: {picked}")
        return picked

    if not attachments_root.exists():
        raise FileNotFoundError(f"附件根目录不存在: {attachments_root}")

    candidates = [
        p
        for p in attachments_root.iterdir()
        if p.is_dir() and (course_name in p.name or p.name.startswith(course_name))
    ]
    preferred = [p for p in candidates if "收集的文件" in p.name]

    if len(preferred) == 1:
        return preferred[0].resolve()
    if len(preferred) > 1:
        joined = "\n".join(f"- {str(p)}" for p in preferred)
        raise ValueError(f"匹配到多个课程附件目录，请手动指定 --attachments:\n{joined}")

    if len(candidates) == 1:
        return candidates[0].resolve()
    if len(candidates) > 1:
        joined = "\n".join(f"- {str(p)}" for p in candidates)
        raise ValueError(f"匹配到多个课程目录，请手动指定 --attachments:\n{joined}")

    raise FileNotFoundError(f"未在 {attachments_root} 下找到课程 '{course_name}' 对应目录")


def load_students_file(students_json_path: Path, label: str) -> list[dict[str, Any]]:
    if not students_json_path.exists():
        raise FileNotFoundError(f"找不到{label}文件: {students_json_path}")
    try:
        students = json.loads(students_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise ValueError(f"{label} JSON 解析失败: {students_json_path}: {err}") from err
    if not isinstance(students, list):
        raise ValueError(f"{label}格式无效（应为数组）: {students_json_path}")
    return students


def load_students(
    students_json_path: Path,
    other_students_json_path: Path | None = None,
) -> tuple[
    dict[str, list[dict[str, str]]],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
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

        student = {
            "班级": class_name,
            "学号": student_no,
            "姓名": raw_name,
            "姓名标准化": name_norm,
        }

        if name_norm in by_name and by_name[name_norm]["学号"] != student_no:
            prev = by_name[name_norm]
            raise ValueError(
                f"基础学生名单存在重名冲突: {prev['学号']}{prev['姓名']} 与 {student_no}{raw_name}"
            )

        by_class.setdefault(class_name, []).append(student)
        by_name[name_norm] = student

    if other_students_json_path and other_students_json_path.exists():
        other_students = load_students_file(other_students_json_path, "其他学生名单")
        for item in other_students:
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
                raise ValueError(
                    f"基础名单与其他名单重名冲突: {prev['学号']}{prev['姓名']} 与 {student_no}{raw_name}"
                )
            if name_norm in other_by_name and other_by_name[name_norm]["学号"] != student_no:
                prev = other_by_name[name_norm]
                raise ValueError(
                    f"其他学生名单存在重名冲突: {prev['学号']}{prev['姓名']} 与 {student_no}{raw_name}"
                )

            other_by_name[name_norm] = student

    return by_class, by_name, other_by_name


def detect_classes_from_excel(
    df: pd.DataFrame,
    col_name: str,
    students_by_name: dict[str, dict[str, str]],
) -> list[str]:
    classes: set[str] = set()
    for raw_name in df[col_name].dropna().astype(str).tolist():
        student = students_by_name.get(normalize_name(raw_name))
        if student:
            classes.add(student["班级"])
    return sorted(classes)


def normalize_class_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    output: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            output.append(text)
    # Keep order deterministic while deduplicating.
    return sorted(set(output))


def resolve_course_classes(
    local_cfg: dict[str, Any],
    course_name: str,
    detected_classes: list[str],
) -> tuple[list[str], bool]:
    changed = False

    course_classes = local_cfg.get("course_classes")
    if not isinstance(course_classes, dict):
        course_classes = {}
        local_cfg["course_classes"] = course_classes
        changed = True

    entry = course_classes.get(course_name)
    locked = False
    configured_classes: list[str] = []

    if isinstance(entry, list):
        configured_classes = normalize_class_list(entry)
    elif isinstance(entry, dict):
        configured_classes = normalize_class_list(entry.get("classes"))
        locked = bool(entry.get("lock", False))

    if locked and configured_classes:
        return configured_classes, changed

    if detected_classes:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        next_entry = {
            "classes": detected_classes,
            "source": "auto",
            "lock": locked,
            "detected_at": now,
        }
        if entry != next_entry:
            course_classes[course_name] = next_entry
            changed = True
        return detected_classes, changed

    if configured_classes:
        return configured_classes, changed

    raise ValueError(
        f"无法自动识别课程 {course_name} 的班级，且配置中没有可用 classes。"
        "请先运行一次包含有效提交记录的数据，或手工在 local.config.json 填写 classes。"
    )


def scope_students_by_classes(
    students_by_class: dict[str, list[dict[str, str]]],
    target_classes: list[str],
) -> dict[str, list[dict[str, str]]]:
    missing = [class_name for class_name in target_classes if class_name not in students_by_class]
    if missing:
        print(f"[!] 学生名单缺少班级: {', '.join(missing)}")

    scoped = {
        class_name: students_by_class[class_name]
        for class_name in target_classes
        if class_name in students_by_class
    }
    if not scoped:
        raise ValueError("课程班级在学生名单中全部缺失，无法统计。")
    return scoped


def resolve_attachment_filename(
    uploaded_value: str,
    attachment_lookup: dict[str, str],
    duplicate_lookup: dict[str, list[str]],
) -> tuple[str, list[str]]:
    uploaded_name = normalize_uploaded_filename(uploaded_value)
    if not uploaded_name:
        return "", []

    key = normalize_filename_key(uploaded_name)
    if key in duplicate_lookup:
        return "", duplicate_lookup[key]

    found = attachment_lookup.get(key, "")
    if found:
        return found, [uploaded_name]
    return "", [uploaded_name]


def format_datetime(value: Any) -> str:
    if pd.isna(value):
        return ""
    return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def analyze_latest_uploaded_filename_uniqueness(
    df: pd.DataFrame,
    col_time: str,
    col_file: str,
    allowed_extensions: tuple[str, ...] | None,
) -> tuple[int, int, dict[str, int]]:
    df_latest = (
        df.sort_values(by=col_time)
        .drop_duplicates(subset=["_homework_label", "_name_norm"], keep="last")
        .copy()
    )
    files = (
        df_latest[col_file]
        .map(normalize_uploaded_filename)
        .astype(str)
        .map(str.strip)
    )
    files = files[files != ""]
    files = files[files.map(lambda name: is_allowed_attachment_filename(name, allowed_extensions))]
    counts = files.value_counts()
    duplicates = counts[counts > 1]
    return len(files), files.nunique(), duplicates.to_dict()


def build_missing_attachment_summary(stat: dict[str, Any]) -> dict[str, Any]:
    by_class: dict[str, list[str]] = {}
    class_stats = stat.get("班级统计", {})
    if isinstance(class_stats, dict):
        for class_name, class_stat in class_stats.items():
            if not isinstance(class_stat, dict):
                continue
            missing_raw = class_stat.get("已交但附件缺失名单", [])
            if not isinstance(missing_raw, list):
                continue
            missing = sorted({str(x).strip() for x in missing_raw if str(x).strip()})
            if missing:
                by_class[str(class_name)] = missing
    other_missing_raw = stat.get("其他已交但附件缺失名单", [])
    if isinstance(other_missing_raw, list):
        other_missing = sorted({str(x).strip() for x in other_missing_raw if str(x).strip()})
        if other_missing:
            by_class["其他"] = other_missing

    total = sum(len(v) for v in by_class.values())
    summary: dict[str, Any] = {
        "总人数": total,
        "班级统计": by_class,
    }
    if total > 0:
        summary["同步提示"] = "检测到表格有提交记录但本地未找到对应附件，请先同步企业微信微盘后按同一作业标签重跑。"
    return summary


def build_invalid_attachment_summary(stat: dict[str, Any]) -> dict[str, Any]:
    by_class: dict[str, list[str]] = {}
    class_stats = stat.get("班级统计", {})
    if isinstance(class_stats, dict):
        for class_name, class_stat in class_stats.items():
            if not isinstance(class_stat, dict):
                continue
            invalid_raw = class_stat.get("无效附件名单", [])
            if not isinstance(invalid_raw, list):
                continue
            invalid = sorted({str(x).strip() for x in invalid_raw if str(x).strip()})
            if invalid:
                by_class[str(class_name)] = invalid
    other_invalid_raw = stat.get("其他无效附件名单", [])
    if isinstance(other_invalid_raw, list):
        other_invalid = sorted({str(x).strip() for x in other_invalid_raw if str(x).strip()})
        if other_invalid:
            by_class["其他"] = other_invalid

    total = sum(len(v) for v in by_class.values())
    summary: dict[str, Any] = {
        "总人数": total,
        "班级统计": by_class,
    }
    if total > 0:
        summary["判定规则"] = f"仅以下后缀算提交: {format_allowed_extensions(stat.get('有效提交后缀配置'))}"
    return summary


def write_missing_attachment_report(
    stats_dir: Path,
    homework_label: str,
    homework_token: str,
    stat: dict[str, Any],
) -> tuple[Path | None, int]:
    summary = build_missing_attachment_summary(stat)
    total = int(summary.get("总人数", 0))
    report_path = stats_dir / f"{homework_token}.missing_attachments.txt"

    if total <= 0:
        if report_path.exists():
            report_path.unlink()
        return None, 0

    by_class = summary.get("班级统计", {})
    lines: list[str] = [
        f"课程: {stat.get('课程', '')}",
        f"作业: {homework_label}",
        f"缺失附件人数: {total}",
        "",
        "以下同学在收集表中有提交记录，但本地同步目录中未找到附件：",
    ]
    if isinstance(by_class, dict):
        for class_name in sorted(by_class.keys()):
            lines.append(f"- {class_name}")
            for student_no in by_class[class_name]:
                lines.append(f"  - {student_no}")
    lines.extend(
        [
            "",
            "详细信息：",
        ]
    )
    details = stat.get("附件缺失详情", [])
    if isinstance(details, list) and details:
        for row in details:
            if not isinstance(row, dict):
                continue
            cls = str(row.get("班级", "")).strip()
            student_no = str(row.get("学号", "")).strip()
            name = str(row.get("姓名", "")).strip()
            raw_field = str(row.get("原始上传字段", "")).strip()
            candidate_names = row.get("候选附件名", [])
            candidates_text = (
                " | ".join(str(x) for x in candidate_names if str(x).strip())
                if isinstance(candidate_names, list)
                else ""
            )
            lines.append(f"- {cls} {student_no} {name}".strip())
            if candidates_text:
                lines.append(f"  候选附件名: {candidates_text}")
            if raw_field:
                lines.append(f"  原始上传字段: {raw_field}")
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "处理建议：",
            "1. 打开企业微信微盘客户端，确认该课程“收集的文件”已同步完成。",
            "2. 同步完成后，按同一作业标签重跑本课程。",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path, total


def write_invalid_attachment_report(
    stats_dir: Path,
    homework_label: str,
    homework_token: str,
    stat: dict[str, Any],
) -> tuple[Path | None, int]:
    summary = build_invalid_attachment_summary(stat)
    total = int(summary.get("总人数", 0))
    report_path = stats_dir / f"{homework_token}.invalid_attachments.txt"

    if total <= 0:
        if report_path.exists():
            report_path.unlink()
        return None, 0

    by_class = summary.get("班级统计", {})
    lines: list[str] = [
        f"课程: {stat.get('课程', '')}",
        f"作业: {homework_label}",
        f"无效附件人数: {total}",
        f"有效提交后缀: {format_allowed_extensions(stat.get('有效提交后缀配置'))}",
        "",
        "以下同学在收集表中有提交记录，也能在本地找到附件，但附件后缀不在有效提交白名单中：",
    ]
    if isinstance(by_class, dict):
        for class_name in sorted(by_class.keys()):
            lines.append(f"- {class_name}")
            for student_no in by_class[class_name]:
                lines.append(f"  - {student_no}")
    lines.extend(
        [
            "",
            "详细信息：",
        ]
    )
    details = stat.get("无效附件详情", [])
    if isinstance(details, list) and details:
        for row in details:
            if not isinstance(row, dict):
                continue
            cls = str(row.get("班级", "")).strip()
            student_no = str(row.get("学号", "")).strip()
            name = str(row.get("姓名", "")).strip()
            raw_field = str(row.get("原始上传字段", "")).strip()
            actual_file = str(row.get("实际附件名", "")).strip()
            actual_ext = str(row.get("实际后缀", "")).strip()
            lines.append(f"- {cls} {student_no} {name}".strip())
            if actual_file:
                lines.append(f"  实际附件名: {actual_file}")
            if actual_ext:
                lines.append(f"  实际后缀: {actual_ext}")
            if raw_field:
                lines.append(f"  原始上传字段: {raw_field}")
    else:
        lines.append("- 无")
    lines.extend(
        [
            "",
            "处理建议：",
            "1. 要求学生重新上传文档类附件，或按需要调整 local.config.json 中的有效提交后缀白名单。",
            "2. 重新运行本课程对应作业标签，刷新统计结果。",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path, total


def build_uploaded_homework_refs(
    df: pd.DataFrame,
    col_file: str,
) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        uploaded_name = normalize_uploaded_filename(row[col_file])
        if not uploaded_name:
            continue
        key = normalize_filename_key(uploaded_name)
        homework_label = str(row.get("_homework_label", "")).strip()
        if not key or not homework_label:
            continue
        refs.setdefault(key, set()).add(homework_label)
    return refs


def write_source_attachment_cleanup_report(
    stats_dir: Path,
    homework_token: str,
    report: dict[str, Any],
) -> Path:
    report_path = stats_dir / f"{homework_token}.source_attachment_cleanup.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def execute_source_attachment_cleanup(
    *,
    df: pd.DataFrame,
    homework_label: str,
    course_name: str,
    col_name: str,
    col_time: str,
    col_file: str,
    attachments_dir: Path,
    attachment_lookup: dict[str, str],
    duplicate_lookup: dict[str, list[str]],
    uploaded_homework_refs: dict[str, set[str]],
    stats_dir: Path,
    homework_token: str,
    mode: str,
) -> tuple[Path, dict[str, Any]]:
    if mode not in {"dry-run", "apply"}:
        raise ValueError(f"未知清理模式: {mode}")

    df_hw = df[df["_homework_label"] == homework_label].copy()
    df_hw = df_hw.sort_values(by=col_time)
    total_rows = len(df_hw)

    unique_entries: dict[str, dict[str, Any]] = {}
    non_empty_rows = 0
    for _, row in df_hw.iterrows():
        uploaded_name = normalize_uploaded_filename(row[col_file])
        if not uploaded_name:
            continue
        non_empty_rows += 1
        key = normalize_filename_key(uploaded_name)
        entry = unique_entries.setdefault(
            key,
            {
                "附件键": key,
                "Excel附件名": uploaded_name,
                "原始上传字段": [],
                "引用记录": [],
            },
        )
        raw_field = str(row[col_file]).strip()
        if raw_field and raw_field not in entry["原始上传字段"]:
            entry["原始上传字段"].append(raw_field)
        record = {
            "姓名": str(row[col_name]).strip(),
            "提交时间": format_datetime(row[col_time]),
        }
        if record not in entry["引用记录"]:
            entry["引用记录"].append(record)

    delete_candidates: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    missing_local: list[dict[str, Any]] = []
    ambiguous_local: list[dict[str, Any]] = []

    for key, entry in sorted(unique_entries.items()):
        other_homeworks = sorted(uploaded_homework_refs.get(key, set()) - {homework_label}, key=parse_homework_order)
        if other_homeworks:
            protected.append(
                {
                    **entry,
                    "保护原因": "其他作业仍在引用同名附件",
                    "引用作业": other_homeworks,
                }
            )
            continue

        if key in duplicate_lookup:
            ambiguous_local.append(
                {
                    **entry,
                    "保护原因": "本地存在同名歧义附件",
                    "本地候选附件名": duplicate_lookup[key],
                }
            )
            continue

        target_file = attachment_lookup.get(key, "")
        if not target_file:
            unresolved.append(
                {
                    **entry,
                    "保护原因": "Excel 中记录了附件名，但当前本地目录未匹配到同名文件",
                }
            )
            continue

        src_path = attachments_dir / target_file
        if not src_path.exists():
            missing_local.append(
                {
                    **entry,
                    "本地附件名": target_file,
                    "保护原因": "本地目录中该文件已不存在",
                }
            )
            continue

        delete_candidates.append(
            {
                **entry,
                "本地附件名": target_file,
                "本地绝对路径": str(src_path.resolve()),
            }
        )

    deleted: list[str] = []
    delete_failures: list[dict[str, Any]] = []
    attachments_root = attachments_dir.resolve()
    if mode == "apply":
        for item in delete_candidates:
            src_path = Path(str(item["本地绝对路径"])).resolve()
            try:
                src_path.relative_to(attachments_root)
            except ValueError:
                delete_failures.append(
                    {
                        "本地附件名": item["本地附件名"],
                        "原因": "目标文件不在课程附件目录内，已拒绝删除",
                    }
                )
                continue
            if not src_path.exists():
                delete_failures.append(
                    {
                        "本地附件名": item["本地附件名"],
                        "原因": "执行删除时文件已不存在",
                    }
                )
                continue
            try:
                src_path.unlink()
                deleted.append(str(item["本地附件名"]))
            except OSError as err:
                delete_failures.append(
                    {
                        "本地附件名": item["本地附件名"],
                        "原因": str(err),
                    }
                )

    report: dict[str, Any] = {
        "课程": course_name,
        "作业": homework_label,
        "模式": mode,
        "统计生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "附件目录": str(attachments_root),
        "汇总": {
            "Excel记录总数": total_rows,
            "Excel非空附件记录数": non_empty_rows,
            "Excel唯一附件数": len(unique_entries),
            "计划删除附件数": len(delete_candidates),
            "实际删除附件数": len(deleted),
            "跨作业保护附件数": len(protected),
            "本地歧义附件数": len(ambiguous_local),
            "未匹配附件数": len(unresolved),
            "本地已不存在附件数": len(missing_local),
            "删除失败附件数": len(delete_failures),
        },
        "计划删除附件": delete_candidates,
        "实际删除附件": deleted,
        "跨作业保护附件": protected,
        "本地歧义附件": ambiguous_local,
        "未匹配附件": unresolved,
        "本地已不存在附件": missing_local,
        "删除失败附件": delete_failures,
    }
    report_path = write_source_attachment_cleanup_report(
        stats_dir=stats_dir,
        homework_token=homework_token,
        report=report,
    )
    return report_path, report


def load_existing_course_homework_stats(
    public_root: Path,
    course_name: str,
) -> dict[str, dict[str, Any]]:
    web_data_root = public_root / "data"
    course_slug = sanitize_filename_component(course_name)
    course_index_path = web_data_root / f"{course_slug}.index.json"
    normalized: dict[str, dict[str, Any]] = {}

    if not course_index_path.exists():
        return {}
    try:
        course_index = json.loads(course_index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    hw_list = course_index.get("作业列表", [])
    if not isinstance(hw_list, list):
        return {}
    for item in hw_list:
        if not isinstance(item, dict):
            continue
        hw_label = str(item.get("作业", "")).strip()
        rel = str(item.get("数据文件", "")).strip()
        if not hw_label or not rel:
            continue
        hw_path = (public_root / rel).resolve()
        if not hw_path.exists():
            continue
        try:
            hw_data = json.loads(hw_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(hw_data, dict):
            normalized[hw_label] = hw_data
    return normalized


def resolve_selected_homework_labels(
    available_labels: list[str],
    requested_labels: list[str],
) -> list[str]:
    normalized_requested = [normalize_homework_label(label) for label in requested_labels]
    normalized_requested = [label for label in normalized_requested if label]
    if not normalized_requested:
        raise ValueError("至少需要指定一个作业标签。")

    available_set = set(available_labels)
    missing = [label for label in normalized_requested if label not in available_set]
    if missing:
        raise ValueError(f"以下作业标签未出现在当前 Excel 中: {', '.join(missing)}")

    selected: list[str] = []
    seen: set[str] = set()
    for label in normalized_requested:
        if label in seen:
            continue
        seen.add(label)
        selected.append(label)
    return selected


def build_final_homework_label_order(
    excel_labels: list[str],
    existing_labels: list[str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for label in excel_labels + existing_labels:
        if label in seen:
            continue
        seen.add(label)
        ordered.append(label)
    return ordered


def make_homework_stat(
    df: pd.DataFrame,
    homework_label: str,
    course_name: str,
    col_name: str,
    col_time: str,
    col_file: str,
    students_by_class: dict[str, list[dict[str, str]]],
    other_students_by_name: dict[str, dict[str, str]],
    attachments_dir: Path,
    attachment_lookup: dict[str, str],
    duplicate_lookup: dict[str, list[str]],
    homework_output_dir: Path,
    output_filename_template: str,
    allowed_submission_extensions: tuple[str, ...] | None,
) -> dict[str, Any] | None:
    df_hw = df[df["_homework_label"] == homework_label].copy()
    if df_hw.empty:
        return None

    df_latest = df_hw.sort_values(by=col_time).drop_duplicates(subset=["_name_norm"], keep="last")
    latest_by_name = {row["_name_norm"]: row for _, row in df_latest.iterrows()}
    latest_record_time = format_datetime(df_hw[col_time].max())
    homework_order = parse_homework_order(homework_label)

    if homework_output_dir.exists():
        shutil.rmtree(homework_output_dir)
    homework_output_dir.mkdir(parents=True, exist_ok=True)

    all_classes = sorted(students_by_class.keys())
    for class_name in all_classes:
        (homework_output_dir / class_name).mkdir(parents=True, exist_ok=True)

    stat: dict[str, Any] = {
        "作业": homework_label,
        "课程": course_name,
        "最后提交时间": "",
        "最后收集记录时间": latest_record_time,
        "统计生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "总班级数": len(all_classes),
        "有效提交后缀配置": (
            list(allowed_submission_extensions) if allowed_submission_extensions is not None else None
        ),
        "班级统计": {},
    }

    total_submit = 0
    total_expected = 0
    total_invalid = 0
    total_attachment_missing = 0
    valid_submit_times: list[Any] = []
    attachment_missing_details: list[dict[str, Any]] = []
    invalid_attachment_details: list[dict[str, Any]] = []

    for class_name in all_classes:
        class_students = students_by_class[class_name]
        submitted: list[str] = []
        not_submitted: list[str] = []
        attachment_missing: list[str] = []
        invalid_attachment: list[str] = []

        for student in class_students:
            student_name = student["姓名"]
            student_name_norm = student["姓名标准化"]
            student_no = student["学号"]

            row = latest_by_name.get(student_name_norm)
            if row is None:
                not_submitted.append(student_no)
                continue

            person_name = str(row[col_name])
            uploaded_value = str(row[col_file]).strip()
            target_file, candidate_files = resolve_attachment_filename(
                uploaded_value=uploaded_value,
                attachment_lookup=attachment_lookup,
                duplicate_lookup=duplicate_lookup,
            )

            if not target_file:
                print(f"  [!] 已交但未匹配到附件: [{person_name}/{student_no}]")
                if candidate_files:
                    print(f"      候选附件名: {' | '.join(candidate_files)}")
                if uploaded_value:
                    print(f"      原始上传字段: {uploaded_value}")
                not_submitted.append(student_no)
                attachment_missing.append(student_no)
                attachment_missing_details.append(
                    {
                        "班级": class_name,
                        "学号": student_no,
                        "姓名": person_name,
                        "候选附件名": candidate_files,
                        "原始上传字段": uploaded_value,
                    }
                )
                continue

            src_path = attachments_dir / target_file
            if not src_path.exists():
                print(f"  [!] 已交但附件不存在: [{person_name}/{student_no}] -> '{target_file}'")
                not_submitted.append(student_no)
                attachment_missing.append(student_no)
                attachment_missing_details.append(
                    {
                        "班级": class_name,
                        "学号": student_no,
                        "姓名": person_name,
                        "候选附件名": [target_file],
                        "原始上传字段": uploaded_value,
                    }
                )
                continue

            ext = normalize_extension(src_path.suffix)
            if allowed_submission_extensions is not None and ext not in allowed_submission_extensions:
                print(f"  [!] 附件后缀不计入提交: [{person_name}/{student_no}] -> '{target_file}' ({ext or '无后缀'})")
                not_submitted.append(student_no)
                invalid_attachment.append(student_no)
                invalid_attachment_details.append(
                    {
                        "班级": class_name,
                        "学号": student_no,
                        "姓名": person_name,
                        "实际附件名": target_file,
                        "实际后缀": ext,
                        "原始上传字段": uploaded_value,
                    }
                )
                continue

            submitted.append(student_no)
            valid_submit_times.append(row[col_time])
            renamed = build_output_filename(
                template=output_filename_template,
                student_no=student_no,
                student_name=student_name,
                class_name=class_name,
                course_name=course_name,
                homework_label=homework_label,
                homework_order=homework_order,
                ext=ext,
            )
            dst_path = homework_output_dir / class_name / renamed
            if dst_path.exists():
                raise ValueError(
                    f"输出文件名冲突: {dst_path}。"
                    "请调整 output_filename_templates，确保同一作业内文件名唯一。"
                )
            shutil.copy2(src_path, dst_path)

        expected_count = len(class_students)
        submit_count = len(submitted)
        missing_count = len(attachment_missing)
        invalid_count = len(invalid_attachment)
        total_expected += expected_count
        total_submit += submit_count
        total_attachment_missing += missing_count
        total_invalid += invalid_count

        stat["班级统计"][class_name] = {
            "应交人数": expected_count,
            "已交人数": submit_count,
            "未交人数": len(not_submitted),
            "提交率": round((submit_count / expected_count) if expected_count else 0, 4),
            "已交名单": submitted,
            "未交名单": not_submitted,
            "已交但附件缺失人数": missing_count,
            "已交但附件缺失名单": sorted(attachment_missing),
            "无效附件人数": invalid_count,
            "无效附件名单": sorted(invalid_attachment),
        }

    other_submitted: list[str] = []
    other_missing: list[str] = []
    other_invalid: list[str] = []
    other_dir = homework_output_dir / "其他"
    for student in other_students_by_name.values():
        student_name_norm = student["姓名标准化"]
        row = latest_by_name.get(student_name_norm)
        if row is None:
            continue
        student_no = student["学号"]
        student_name = student["姓名"]

        uploaded_value = str(row[col_file]).strip()
        target_file, candidate_files = resolve_attachment_filename(
            uploaded_value=uploaded_value,
            attachment_lookup=attachment_lookup,
            duplicate_lookup=duplicate_lookup,
        )
        if not target_file:
            print(f"  [!] 其他同学已交但未匹配到附件: [{student_name}/{student_no}]")
            if candidate_files:
                print(f"      候选附件名: {' | '.join(candidate_files)}")
            if uploaded_value:
                print(f"      原始上传字段: {uploaded_value}")
            other_missing.append(student_no)
            attachment_missing_details.append(
                {
                    "班级": "其他",
                    "学号": student_no,
                    "姓名": student_name,
                    "候选附件名": candidate_files,
                    "原始上传字段": uploaded_value,
                }
            )
            continue

        src_path = attachments_dir / target_file
        if not src_path.exists():
            print(f"  [!] 其他同学已交但附件不存在: [{student_name}/{student_no}] -> '{target_file}'")
            other_missing.append(student_no)
            attachment_missing_details.append(
                {
                    "班级": "其他",
                    "学号": student_no,
                    "姓名": student_name,
                    "候选附件名": [target_file],
                    "原始上传字段": uploaded_value,
                }
            )
            continue

        if not other_dir.exists():
            other_dir.mkdir(parents=True, exist_ok=True)

        ext = normalize_extension(src_path.suffix)
        if allowed_submission_extensions is not None and ext not in allowed_submission_extensions:
            print(f"  [!] 其他同学附件后缀不计入提交: [{student_name}/{student_no}] -> '{target_file}' ({ext or '无后缀'})")
            other_invalid.append(student_no)
            invalid_attachment_details.append(
                {
                    "班级": "其他",
                    "学号": student_no,
                    "姓名": student_name,
                    "实际附件名": target_file,
                    "实际后缀": ext,
                    "原始上传字段": uploaded_value,
                }
            )
            continue

        other_submitted.append(student_no)
        valid_submit_times.append(row[col_time])
        renamed = build_output_filename(
            template=output_filename_template,
            student_no=student_no,
            student_name=student_name,
            class_name="其他",
            course_name=course_name,
            homework_label=homework_label,
            homework_order=homework_order,
            ext=ext,
        )
        dst_path = other_dir / renamed
        if dst_path.exists():
            raise ValueError(
                f"输出文件名冲突: {dst_path}。"
                "请调整 output_filename_templates，确保同一作业内文件名唯一。"
            )
        shutil.copy2(src_path, dst_path)

    if valid_submit_times:
        stat["最后提交时间"] = format_datetime(max(valid_submit_times))
    stat["其他已交名单"] = sorted(set(other_submitted))
    stat["其他已交但附件缺失名单"] = sorted(set(other_missing))
    stat["其他无效附件名单"] = sorted(set(other_invalid))

    stat["汇总"] = {
        "应交总人数": total_expected,
        "已交总人数": total_submit,
        "未交总人数": total_expected - total_submit,
        "总提交率": round((total_submit / total_expected) if total_expected else 0, 4),
        "已交但附件缺失总人数": total_attachment_missing,
        "无效附件总人数": total_invalid,
    }
    stat["附件缺失"] = build_missing_attachment_summary(stat)
    stat["无效附件"] = build_invalid_attachment_summary(stat)
    if attachment_missing_details:
        stat["附件缺失详情"] = attachment_missing_details
    if invalid_attachment_details:
        stat["无效附件详情"] = invalid_attachment_details
    return stat


def write_course_web_data(
    web_data_root: Path,
    course_index_path: Path,
    course_name: str,
    homework_stats: dict[str, dict[str, Any]],
    ordered_homework_labels: list[str],
    homework_tokens: dict[str, str],
) -> None:
    web_data_root.mkdir(parents=True, exist_ok=True)
    course_index_path.parent.mkdir(parents=True, exist_ok=True)

    course_slug = sanitize_filename_component(course_name)

    keep_homework_filenames: set[str] = set()
    course_homework_list: list[dict[str, str]] = []

    for hw_label in ordered_homework_labels:
        hw_stat = homework_stats.get(hw_label)
        if hw_stat is None:
            continue
        homework_token = homework_tokens[hw_label]
        hw_filename = f"{course_slug}.{homework_token}.json"
        keep_homework_filenames.add(hw_filename)

        hw_relative_path = f"data/{hw_filename}"
        hw_payload = dict(hw_stat)
        # 保持前端公开数据最小化：缺失详情仅用于本地排障，不对外发布。
        hw_payload.pop("附件缺失详情", None)
        hw_payload.pop("无效附件详情", None)
        hw_payload.setdefault("作业", hw_label)
        hw_payload.setdefault("课程", course_name)
        hw_payload["更新时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        (web_data_root / hw_filename).write_text(
            json.dumps(hw_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        course_homework_list.append({"作业": hw_label, "数据文件": hw_relative_path})

    course_index_filename = f"{course_slug}.index.json"
    for old_file in web_data_root.glob(f"{course_slug}.*.json"):
        if old_file.name == course_index_filename:
            continue
        if old_file.name in keep_homework_filenames:
            continue
        old_file.unlink()

    # Remove legacy monolithic course file after migration.
    legacy_course_file = web_data_root / f"{course_slug}.json"
    if legacy_course_file.exists():
        legacy_course_file.unlink()

    course_relative_path = f"data/{course_index_filename}"
    course_data = {
        "课程": course_name,
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "作业列表": course_homework_list,
    }
    (web_data_root / course_index_filename).write_text(
        json.dumps(course_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if course_index_path.exists():
        try:
            index_data = json.loads(course_index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            index_data = {}
    else:
        index_data = {}

    course_list = index_data.get("课程列表", [])
    if not isinstance(course_list, list):
        course_list = []

    merged: dict[str, dict[str, str]] = {}
    for item in course_list:
        name = str(item.get("课程", "")).strip()
        data_file = str(item.get("数据文件", "")).strip()
        if name and data_file:
            merged[name] = {"课程": name, "数据文件": data_file}

    merged[course_name] = {"课程": course_name, "数据文件": course_relative_path}

    new_index = {
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "课程列表": [merged[k] for k in sorted(merged.keys())],
    }
    course_index_path.write_text(json.dumps(new_index, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    parser = argparse.ArgumentParser(description="按课程批量提取所有作业并输出统计。")
    parser.add_argument(
        "--config",
        default=str(repo_root / "config" / "local.config.json"),
        help="本地配置 JSON 路径（用于配置所有本地路径）",
    )
    parser.add_argument("--course", default="", help="课程名（默认自动检测，多个课程时必填）")
    parser.add_argument("--excel", default="", help="指定课程 Excel 路径，优先级高于 --course")
    parser.add_argument("--list-courses", action="store_true", help="仅列出 config 下可选课程")
    parser.add_argument("--list-homework-labels", action="store_true", help="仅列出当前课程 Excel 中可选的作业标签")
    parser.add_argument(
        "--label",
        dest="labels",
        action="append",
        default=[],
        help="指定要处理的作业标签，可重复传入多次",
    )
    parser.add_argument("--courses-dir", default="", help="课程 Excel 所在目录（默认读取配置项 courses_dir）")
    parser.add_argument(
        "--attachments-root",
        default="",
        help="企业微信课程目录上级路径",
    )
    parser.add_argument("--attachments", default="", help="直接指定课程附件目录（可覆盖自动匹配）")
    parser.add_argument("--students", default="", help="学生名单 JSON 路径")
    parser.add_argument(
        "--other-students",
        default="",
        help="其他学生名单 JSON 路径（如重修/补修）",
    )
    parser.add_argument("--out-root", default="", help="输出根目录（会在其下创建课程目录）")
    parser.add_argument("--web-data-root", default="", help="webapp 课程 JSON 输出目录")
    parser.add_argument("--course-index", default="", help="webapp 课程索引 JSON 路径")
    parser.add_argument(
        "--cleanup-source-attachments",
        choices=["off", "dry-run", "apply"],
        default="off",
        help="按 Excel 中当前所选作业标签的全部附件记录清理课程同步目录中的源文件",
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="仅执行源附件清理，不重跑提取和 web 数据输出",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    local_config_path = Path(args.config).expanduser().resolve()
    local_cfg = load_local_config(local_config_path)

    courses_dir = resolve_path(
        pick_setting(args.courses_dir, local_cfg, "courses_dir", str(repo_root / "config")),
        repo_root,
    )
    if args.list_courses and not courses_dir.exists():
        raise FileNotFoundError(f"课程目录不存在: {courses_dir}")

    config_dir = courses_dir
    courses = discover_courses(config_dir)

    if args.list_courses:
        if not courses:
            print("config 下没有可用课程 Excel。")
            return
        print("可选课程:")
        for name, path in courses.items():
            print(f"- {name} -> {path}")
        return

    course_name, excel_path = choose_course_excel(courses, args.course, args.excel)

    attachments_root_text = pick_setting(args.attachments_root, local_cfg, "attachments_root")
    if not attachments_root_text:
        raise ValueError("缺少 attachments_root，请在 --config 或 --attachments-root 中提供。")

    attachments_root = resolve_path(attachments_root_text, repo_root)
    attachments_override = pick_setting(args.attachments, local_cfg, "attachments")
    attachments_dir = find_attachments_dir(course_name, attachments_root, attachments_override)

    students_text = pick_setting(
        args.students,
        local_cfg,
        "students",
        str(repo_root / "config" / "students.json"),
    )
    other_students_text = pick_setting(
        args.other_students,
        local_cfg,
        "other_students",
        str(repo_root / "config" / "other_students.json"),
    )
    out_root_text = pick_setting(args.out_root, local_cfg, "out_root", str(repo_root / "out"))
    web_data_root_text = pick_setting(
        args.web_data_root,
        local_cfg,
        "web_data_root",
        str(repo_root / "webapp" / "public" / "data"),
    )
    course_index_text = pick_setting(
        args.course_index,
        local_cfg,
        "course_index",
        str(repo_root / "webapp" / "public" / "courses.json"),
    )

    students_path = resolve_path(students_text, repo_root)
    other_students_path = resolve_path(other_students_text, repo_root)
    out_root = resolve_path(out_root_text, repo_root)
    web_data_root = resolve_path(web_data_root_text, repo_root)
    course_index_path = resolve_path(course_index_text, repo_root)
    output_filename_template = resolve_course_template(
        local_cfg,
        "output_filename_templates",
        course_name,
        "{student_no}{student_name}{ext}",
    )
    zip_name_template = resolve_course_template(
        local_cfg,
        "zip_name_templates",
        course_name,
        "{course_name}-{homework_label}",
    )
    allowed_submission_extensions = resolve_course_extension_allowlist(
        local_cfg,
        "allowed_submission_extensions",
        course_name,
        DEFAULT_ALLOWED_SUBMISSION_EXTENSIONS,
    )
    zip_enabled = parse_bool_setting(local_cfg.get("zip_enabled"), True)
    cleanup_mode = args.cleanup_source_attachments
    if args.cleanup_only and cleanup_mode == "off":
        raise ValueError("--cleanup-only 必须搭配 --cleanup-source-attachments dry-run/apply 使用。")

    print(f">>> 课程: {course_name}")
    print(f">>> Excel: {excel_path}")
    print(f">>> 附件目录: {attachments_dir}")
    print(f">>> 输出命名模板: {output_filename_template}")
    print(f">>> 有效提交后缀: {format_allowed_extensions(allowed_submission_extensions)}")
    if args.cleanup_only:
        print(f">>> 运行模式: 仅清理源附件（{cleanup_mode}）")
    if zip_enabled:
        print(f">>> 压缩包模板: {zip_name_template}")
    else:
        print(">>> 压缩包输出: 已关闭（zip_enabled=false）")

    df = pd.read_excel(excel_path)
    col_name = next((c for c in df.columns if "填写人" in c), None)
    col_time = next((c for c in df.columns if "填写时间" in c), None)
    col_hw = next((c for c in df.columns if "本次提交的是哪次作业" in c), None)
    col_file = next((c for c in df.columns if "请上传作业文件" in c), None)

    if not all([col_name, col_time, col_hw, col_file]):
        raise ValueError("无法在Excel中找到需要的列，请检查文件内容。")

    df = df.copy()
    df[col_time] = pd.to_datetime(df[col_time], errors="coerce")
    df["_homework_label"] = df[col_hw].astype(str).map(normalize_homework_label)
    df["_name_norm"] = df[col_name].astype(str).map(normalize_name)
    homework_labels = discover_homework_labels(df)
    if args.list_homework_labels:
        if not homework_labels:
            print("当前课程 Excel 中没有可用的作业标签。")
            return
        print("可选作业标签:")
        for idx, label in enumerate(homework_labels, start=1):
            print(f"[{idx}] {label}")
        return

    selected_homework_labels = resolve_selected_homework_labels(
        available_labels=homework_labels,
        requested_labels=args.labels,
    )

    attachment_lookup, duplicate_lookup = build_attachment_lookup(attachments_dir)
    print(
        ">>> 本地附件索引:"
        f" 唯一文件={len(attachment_lookup)}, 同名冲突键={len(duplicate_lookup)}"
    )
    if duplicate_lookup:
        print("  [!] 本地附件存在同名冲突（仅显示前10项）：")
        for idx, (key, names) in enumerate(sorted(duplicate_lookup.items())):
            if idx >= 10:
                break
            print(f"      - {key}: {' | '.join(names)}")

    course_out_dir = out_root / course_name
    course_out_dir.mkdir(parents=True, exist_ok=True)
    stats_dir = course_out_dir / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)

    if homework_labels:
        print(f">>> Excel检测到作业: {', '.join(homework_labels)}")
    else:
        print(">>> 该课程 Excel 暂无作业记录。")
    print(f">>> 本次处理标签: {', '.join(selected_homework_labels)}")

    uploaded_homework_refs = build_uploaded_homework_refs(df=df, col_file=col_file)
    existing_stats = load_existing_course_homework_stats(
        public_root=course_index_path.parent,
        course_name=course_name,
    )
    final_homework_labels = build_final_homework_label_order(
        excel_labels=homework_labels,
        existing_labels=list(existing_stats.keys()),
    )
    homework_tokens = build_homework_path_tokens(final_homework_labels)

    if args.cleanup_only:
        cleanup_reports: list[tuple[str, Path, dict[str, Any]]] = []
        for hw in selected_homework_labels:
            report_path, cleanup_report = execute_source_attachment_cleanup(
                df=df,
                homework_label=hw,
                course_name=course_name,
                col_name=col_name,
                col_time=col_time,
                col_file=col_file,
                attachments_dir=attachments_dir,
                attachment_lookup=attachment_lookup,
                duplicate_lookup=duplicate_lookup,
                uploaded_homework_refs=uploaded_homework_refs,
                stats_dir=stats_dir,
                homework_token=homework_tokens[hw],
                mode=cleanup_mode,
            )
            cleanup_reports.append((hw, report_path, cleanup_report))
        print("\n源附件清理完成！")
        if not cleanup_reports:
            print("- 当前标签在 Excel 中没有可清理的作业记录。")
            return
        for hw, report_path, cleanup_report in cleanup_reports:
            summary = cleanup_report.get("汇总", {})
            print(
                f"- {hw}: 计划删除 {summary.get('计划删除附件数', 0)}，"
                f"实际删除 {summary.get('实际删除附件数', 0)}，"
                f"跨作业保护 {summary.get('跨作业保护附件数', 0)}，"
                f"报告 {report_path}"
            )
        return

    students_by_class, students_by_name, other_students_by_name = load_students(
        students_json_path=students_path,
        other_students_json_path=other_students_path if other_students_text else None,
    )
    if other_students_by_name:
        print(f">>> 其他名单人数: {len(other_students_by_name)}")
    if not students_by_class:
        raise ValueError("学生名单为空，无法统计提交情况。")

    detected_classes = detect_classes_from_excel(df, col_name, students_by_name)
    target_classes, cfg_changed = resolve_course_classes(local_cfg, course_name, detected_classes)
    students_by_class = scope_students_by_classes(students_by_class, target_classes)
    print(f">>> 统计班级: {', '.join(sorted(students_by_class.keys()))}")
    if cfg_changed:
        save_local_config(local_config_path, local_cfg)
        print(f">>> 已自动更新课程班级配置: {local_config_path}")

    latest_file_total, latest_file_unique, latest_file_duplicates = analyze_latest_uploaded_filename_uniqueness(
        df=df,
        col_time=col_time,
        col_file=col_file,
        allowed_extensions=allowed_submission_extensions,
    )
    print(
        ">>> Excel有效附件名唯一性（按每位同学每次作业最新记录）:"
        f" 非空={latest_file_total}, 唯一={latest_file_unique}, 重复={len(latest_file_duplicates)}"
    )
    if latest_file_duplicates:
        print("  [!] 检测到重复的有效附件名（将标记为歧义并阻止提取）：")
        for file_name, count in sorted(latest_file_duplicates.items(), key=lambda kv: kv[1], reverse=True)[:10]:
            print(f"      - {file_name} x{count}")
        duplicate_preview = ", ".join(
            [f"{name} x{count}" for name, count in sorted(latest_file_duplicates.items(), key=lambda kv: kv[1], reverse=True)[:10]]
        )
        raise ValueError(
            "Excel 最新记录存在重复的有效附件名，无法保证一一匹配，请先修正命名后重跑。"
            f"示例: {duplicate_preview}"
        )

    all_stats: dict[str, dict[str, Any]] = {}
    for hw, stat in existing_stats.items():
        if hw not in selected_homework_labels:
            all_stats[hw] = stat

    missing_attachment_reports: list[tuple[str, Path, int]] = []
    invalid_attachment_reports: list[tuple[str, Path, int]] = []
    cleanup_reports: list[tuple[str, Path, dict[str, Any]]] = []
    generated_zip_files: list[Path] = []
    zip_output_dir = course_out_dir / "zip"

    for hw in selected_homework_labels:
        print(f"\n>>> 开始处理 {course_name} {hw}")
        hw_token = homework_tokens[hw]
        hw_dir = course_out_dir / f"{hw_token}作业"
        stat = make_homework_stat(
            df=df,
            homework_label=hw,
            course_name=course_name,
            col_name=col_name,
            col_time=col_time,
            col_file=col_file,
            students_by_class=students_by_class,
            other_students_by_name=other_students_by_name,
            attachments_dir=attachments_dir,
            attachment_lookup=attachment_lookup,
            duplicate_lookup=duplicate_lookup,
            homework_output_dir=hw_dir,
            output_filename_template=output_filename_template,
            allowed_submission_extensions=allowed_submission_extensions,
        )
        if stat is None:
            if hw in existing_stats:
                print(f"  [!] {hw} 在Excel中无可用记录，保留历史统计。")
                all_stats[hw] = existing_stats[hw]
            else:
                print(f"  [!] {hw} 在Excel中无可用记录，且无历史统计。")
            continue

        all_stats[hw] = stat
        hw_stat_file = stats_dir / f"{hw_token}.json"
        hw_stat_file.write_text(json.dumps(stat, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"√ 已输出: {hw_stat_file}")
        if zip_enabled:
            zip_filename = build_zip_filename(
                template=zip_name_template,
                course_name=course_name,
                homework_label=hw,
                homework_order=parse_homework_order(hw),
            )
            zip_path = create_homework_zip(
                homework_output_dir=hw_dir,
                zip_dir=zip_output_dir,
                zip_filename=zip_filename,
            )
            generated_zip_files.append(zip_path)
            print(f"√ 已打包: {zip_path}")

        missing_report_path, missing_total = write_missing_attachment_report(
            stats_dir=stats_dir,
            homework_label=hw,
            homework_token=hw_token,
            stat=stat,
        )
        if missing_report_path is not None and missing_total > 0:
            missing_attachment_reports.append((hw, missing_report_path, missing_total))
            print(f"  [!] {hw} 检测到附件缺失 {missing_total} 人")
            print(f"  [!] 缺失报告: {missing_report_path}")
            details = stat.get("附件缺失详情", [])
            if isinstance(details, list):
                for row in details:
                    if not isinstance(row, dict):
                        continue
                    cls = str(row.get("班级", "")).strip()
                    student_no = str(row.get("学号", "")).strip()
                    name = str(row.get("姓名", "")).strip()
                    candidate_names = row.get("候选附件名", [])
                    candidates_text = (
                        " | ".join(str(x) for x in candidate_names if str(x).strip())
                        if isinstance(candidate_names, list)
                        else ""
                    )
                    detail_line = f"      - {cls} {student_no} {name}".rstrip()
                    if candidates_text:
                        detail_line += f" | 候选附件: {candidates_text}"
                    print(detail_line)
            print("  [!] 请先同步企业微信微盘，再按同一作业标签重跑。")

        invalid_report_path, invalid_total = write_invalid_attachment_report(
            stats_dir=stats_dir,
            homework_label=hw,
            homework_token=hw_token,
            stat=stat,
        )
        if invalid_report_path is not None and invalid_total > 0:
            invalid_attachment_reports.append((hw, invalid_report_path, invalid_total))
            print(f"  [!] {hw} 检测到无效附件 {invalid_total} 人")
            print(f"  [!] 无效附件报告: {invalid_report_path}")
            invalid_details = stat.get("无效附件详情", [])
            if isinstance(invalid_details, list):
                for row in invalid_details:
                    if not isinstance(row, dict):
                        continue
                    cls = str(row.get("班级", "")).strip()
                    student_no = str(row.get("学号", "")).strip()
                    name = str(row.get("姓名", "")).strip()
                    actual_file = str(row.get("实际附件名", "")).strip()
                    actual_ext = str(row.get("实际后缀", "")).strip()
                    detail_line = f"      - {cls} {student_no} {name}".rstrip()
                    if actual_file:
                        detail_line += f" | 实际附件: {actual_file}"
                    if actual_ext:
                        detail_line += f" | 后缀: {actual_ext}"
                    print(detail_line)
            print("  [!] 这些附件不会计入提交率；如有需要，请修改配置白名单或要求学生重传。")

    if not all_stats:
        print("  [!] 当前课程无可用统计，输出将为空。")
    elif missing_attachment_reports:
        print("\n>>> 附件缺失汇总（请先同步微盘后重跑）")
        for hw, report_path, count in missing_attachment_reports:
            print(f"- {hw}: 缺失 {count} 人 -> {report_path}")
    if invalid_attachment_reports:
        print("\n>>> 无效附件汇总（未计入提交率）")
        for hw, report_path, count in invalid_attachment_reports:
            print(f"- {hw}: 无效 {count} 人 -> {report_path}")
    if cleanup_mode != "off":
        for hw in selected_homework_labels:
            report_path, cleanup_report = execute_source_attachment_cleanup(
                df=df,
                homework_label=hw,
                course_name=course_name,
                col_name=col_name,
                col_time=col_time,
                col_file=col_file,
                attachments_dir=attachments_dir,
                attachment_lookup=attachment_lookup,
                duplicate_lookup=duplicate_lookup,
                uploaded_homework_refs=uploaded_homework_refs,
                stats_dir=stats_dir,
                homework_token=homework_tokens[hw],
                mode=cleanup_mode,
            )
            cleanup_reports.append((hw, report_path, cleanup_report))
    if cleanup_reports:
        print(f"\n>>> 源附件清理汇总（模式: {cleanup_mode}）")
        for hw, report_path, cleanup_report in cleanup_reports:
            summary = cleanup_report.get("汇总", {})
            print(
                f"- {hw}: 计划删除 {summary.get('计划删除附件数', 0)}，"
                f"实际删除 {summary.get('实际删除附件数', 0)}，"
                f"跨作业保护 {summary.get('跨作业保护附件数', 0)} -> {report_path}"
            )

    summary_path = course_out_dir / "course_summary.json"
    summary_data = {
        "课程": course_name,
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "作业列表": [label for label in final_homework_labels if label in all_stats],
        "统计文件目录": str(stats_dir),
    }
    if zip_enabled:
        summary_data["压缩包目录"] = str(zip_output_dir)
        summary_data["压缩包列表"] = [str(path) for path in generated_zip_files]
    summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")

    write_course_web_data(
        web_data_root=web_data_root,
        course_index_path=course_index_path,
        course_name=course_name,
        homework_stats=all_stats,
        ordered_homework_labels=final_homework_labels,
        homework_tokens=homework_tokens,
    )
    manifest_result = rebuild_course_manifest(
        public_root=course_index_path.parent,
        course_index_path=course_index_path,
    )

    print("\n处理完成！")
    print(f"- 课程输出目录: {course_out_dir}")
    print(f"- 单次作业统计目录: {stats_dir}")
    if zip_enabled:
        if generated_zip_files:
            print("- 本次生成压缩包:")
            for zip_path in generated_zip_files:
                print(f"  - {zip_path}")
        else:
            print(f"- 本次未生成压缩包（目录: {zip_output_dir}）")
    print(f"- 课程汇总: {summary_path}")
    print(f"- web 课程作业索引: {web_data_root / (sanitize_filename_component(course_name) + '.index.json')}")
    print(f"- web 课程索引: {course_index_path}")
    print(f"- web manifest: {manifest_result['manifest_file']}")
    print(f"- web 版本索引: {manifest_result['index_file']}")


if __name__ == "__main__":
    main()
