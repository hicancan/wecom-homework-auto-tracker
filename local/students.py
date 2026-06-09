from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from contract import normalize_name


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
        raise ValueError(f"无法从对象或 Excel 检测班级: {meta['标题']}")
    return target


def scope_students_by_classes(
    students_by_class: dict[str, list[dict[str, str]]],
    target_classes: list[str],
) -> dict[str, list[dict[str, str]]]:
    missing = [class_name for class_name in target_classes if class_name not in students_by_class]
    if missing:
        raise ValueError(f"学生名单缺少班级: {', '.join(missing)}")
    return {class_name: students_by_class[class_name] for class_name in target_classes}
