# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pandas",
#     "openpyxl",
#     "requests",
# ]
# ///
import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pandas as pd
import requests
from course_manifest import rebuild_course_manifest


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


def get_exact_filename_from_url(url: str) -> str:
    """访问腾讯微盘分享链接，从网页 <title> 提取同步后的精确文件名。"""
    url = url.strip()
    if not url.startswith("http"):
        return url

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        match = re.search(r"<title>(.*?)</title>", response.text)
        if match:
            title = match.group(1).strip()
            if title and "微信" not in title and "腾讯" not in title:
                return title
    except Exception as err:
        print(f"  [!] 获取URL文件名失败: {err}")
    return ""


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name)).strip()


def sanitize_filename_component(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(text)).strip()


def parse_homework_order(hw_name: str) -> int:
    match = re.search(r"(\d+)", str(hw_name))
    return int(match.group(1)) if match else 10**9


def normalize_homework_label(value: str) -> str:
    raw = str(value).strip()
    match = re.search(r"(\d+)", raw)
    if match:
        return f"第{match.group(1)}次"
    return raw


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
    file_url: str,
    files_in_dir: list[str],
) -> str:
    candidates: list[str] = []

    title_name = get_exact_filename_from_url(file_url)
    if title_name:
        candidates.append(title_name)

    if file_url.startswith("http"):
        path_name = unquote(os.path.basename(urlparse(file_url).path or "")).strip()
        if path_name:
            candidates.append(path_name)
    elif file_url:
        candidates.append(file_url.strip())

    for candidate in candidates:
        if candidate in files_in_dir:
            return candidate

    return ""


def format_datetime(value: Any) -> str:
    if pd.isna(value):
        return ""
    return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


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
    homework_output_dir: Path,
) -> dict[str, Any] | None:
    df_hw = df[df["_homework_label"] == homework_label].copy()
    if df_hw.empty:
        return None

    df_hw[col_time] = pd.to_datetime(df_hw[col_time])
    df_hw["_name_norm"] = df_hw[col_name].astype(str).map(normalize_name)
    df_latest = df_hw.sort_values(by=col_time).drop_duplicates(subset=["_name_norm"], keep="last")
    latest_by_name = {row["_name_norm"]: row for _, row in df_latest.iterrows()}
    latest_submit_time = format_datetime(df_hw[col_time].max())

    if homework_output_dir.exists():
        shutil.rmtree(homework_output_dir)
    homework_output_dir.mkdir(parents=True, exist_ok=True)

    all_classes = sorted(students_by_class.keys())
    for class_name in all_classes:
        (homework_output_dir / class_name).mkdir(parents=True, exist_ok=True)

    files_in_dir = os.listdir(attachments_dir)

    stat: dict[str, Any] = {
        "作业": homework_label,
        "课程": course_name,
        "最后提交时间": latest_submit_time,
        "统计生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "总班级数": len(all_classes),
        "班级统计": {},
    }

    total_submit = 0
    total_expected = 0

    for class_name in all_classes:
        class_students = students_by_class[class_name]
        submitted: list[str] = []
        not_submitted: list[str] = []

        for student in class_students:
            student_name = student["姓名"]
            student_name_norm = student["姓名标准化"]
            student_no = student["学号"]

            row = latest_by_name.get(student_name_norm)
            if row is None:
                not_submitted.append(student_no)
                continue

            person_name = str(row[col_name])
            file_url = str(row[col_file])
            target_file = resolve_attachment_filename(
                file_url=file_url,
                files_in_dir=files_in_dir,
            )

            if not target_file:
                print(f"  彻底未找到 [{person_name}] 的可用附件！")
                not_submitted.append(student_no)
                continue

            if target_file not in files_in_dir:
                print(f"[{person_name}] Excel指向文件 '{target_file}' 在同步目录不存在！")
                not_submitted.append(student_no)
                continue

            src_path = attachments_dir / target_file
            ext = src_path.suffix
            renamed = f"{student_no}{sanitize_filename_component(student_name)}{ext}"
            dst_path = homework_output_dir / class_name / renamed
            shutil.copy2(src_path, dst_path)
            submitted.append(student_no)

        expected_count = len(class_students)
        submit_count = len(submitted)
        total_expected += expected_count
        total_submit += submit_count

        stat["班级统计"][class_name] = {
            "应交人数": expected_count,
            "已交人数": submit_count,
            "未交人数": len(not_submitted),
            "提交率": round((submit_count / expected_count) if expected_count else 0, 4),
            "已交名单": submitted,
            "未交名单": not_submitted,
        }

    other_submitted: list[str] = []
    for student in other_students_by_name.values():
        student_name_norm = student["姓名标准化"]
        row = latest_by_name.get(student_name_norm)
        if row is None:
            continue
        file_url = str(row[col_file])
        target_file = resolve_attachment_filename(file_url=file_url, files_in_dir=files_in_dir)
        if not target_file:
            continue
        if target_file not in files_in_dir:
            continue
        other_submitted.append(student["学号"])
    stat["其他已交名单"] = sorted(set(other_submitted))

    stat["汇总"] = {
        "应交总人数": total_expected,
        "已交总人数": total_submit,
        "未交总人数": total_expected - total_submit,
        "总提交率": round((total_submit / total_expected) if total_expected else 0, 4),
    }
    return stat


def write_course_web_data(
    web_data_root: Path,
    course_index_path: Path,
    course_name: str,
    homework_stats: dict[str, dict[str, Any]],
) -> None:
    web_data_root.mkdir(parents=True, exist_ok=True)
    course_index_path.parent.mkdir(parents=True, exist_ok=True)

    sorted_homework = dict(
        sorted(homework_stats.items(), key=lambda kv: parse_homework_order(kv[0]))
    )

    course_filename = f"{sanitize_filename_component(course_name)}.json"
    course_relative_path = f"data/{course_filename}"
    course_data = {
        "课程": course_name,
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "作业统计": sorted_homework,
    }
    (web_data_root / course_filename).write_text(
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

    print(f">>> 课程: {course_name}")
    print(f">>> Excel: {excel_path}")
    print(f">>> 附件目录: {attachments_dir}")

    students_by_class, students_by_name, other_students_by_name = load_students(
        students_json_path=students_path,
        other_students_json_path=other_students_path if other_students_text else None,
    )
    if other_students_by_name:
        print(f">>> 其他名单人数: {len(other_students_by_name)}")
    if not students_by_class:
        raise ValueError("学生名单为空，无法统计提交情况。")

    df = pd.read_excel(excel_path)
    col_name = next((c for c in df.columns if "填写人" in c), None)
    col_time = next((c for c in df.columns if "填写时间" in c), None)
    col_hw = next((c for c in df.columns if "本次提交的是哪次作业" in c), None)
    col_file = next((c for c in df.columns if "请上传作业文件" in c), None)

    if not all([col_name, col_time, col_hw, col_file]):
        raise ValueError("无法在Excel中找到需要的列，请检查文件内容。")

    detected_classes = detect_classes_from_excel(df, col_name, students_by_name)
    target_classes, cfg_changed = resolve_course_classes(local_cfg, course_name, detected_classes)
    students_by_class = scope_students_by_classes(students_by_class, target_classes)
    print(f">>> 统计班级: {', '.join(sorted(students_by_class.keys()))}")
    if cfg_changed:
        save_local_config(local_config_path, local_cfg)
        print(f">>> 已自动更新课程班级配置: {local_config_path}")

    df = df.copy()
    df["_homework_label"] = df[col_hw].astype(str).map(normalize_homework_label)
    homework_labels = sorted(
        [x for x in df["_homework_label"].dropna().unique() if str(x).strip()],
        key=parse_homework_order,
    )

    course_out_dir = out_root / course_name
    course_out_dir.mkdir(parents=True, exist_ok=True)
    stats_dir = course_out_dir / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)

    all_stats: dict[str, dict[str, Any]] = {}

    if not homework_labels:
        print(">>> 该课程 Excel 暂无作业记录，将仅更新课程索引和空课程数据。")
    else:
        print(f">>> 检测到作业: {', '.join(homework_labels)}")
        for hw in homework_labels:
            print(f"\n>>> 开始处理 {course_name} {hw}")
            hw_dir = course_out_dir / f"{hw}作业"
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
                homework_output_dir=hw_dir,
            )
            if stat is None:
                continue

            all_stats[hw] = stat
            hw_stat_file = stats_dir / f"{hw}.json"
            hw_stat_file.write_text(json.dumps(stat, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"√ 已输出: {hw_stat_file}")

    summary_path = course_out_dir / "course_summary.json"
    summary_data = {
        "课程": course_name,
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "作业列表": sorted(all_stats.keys(), key=parse_homework_order),
        "统计文件目录": str(stats_dir),
    }
    summary_path.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")

    write_course_web_data(
        web_data_root=web_data_root,
        course_index_path=course_index_path,
        course_name=course_name,
        homework_stats=all_stats,
    )
    manifest_result = rebuild_course_manifest(
        public_root=course_index_path.parent,
        course_index_path=course_index_path,
    )

    print("\n处理完成！")
    print(f"- 课程输出目录: {course_out_dir}")
    print(f"- 单次作业统计目录: {stats_dir}")
    print(f"- 课程汇总: {summary_path}")
    print(f"- web 课程数据: {web_data_root / (sanitize_filename_component(course_name) + '.json')}")
    print(f"- web 课程索引: {course_index_path}")
    print(f"- web manifest: {manifest_result['manifest_file']}")
    print(f"- web 哈希索引: {manifest_result['index_file']}")


if __name__ == "__main__":
    main()
