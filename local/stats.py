from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from archive import accepted_entry_for, active_entry_for
from contract import format_datetime, now_text, parse_datetime_text, sanitize_filename_component
from web_publish import read_json_object


def load_existing_submission_cutoffs(web_data_root: Path, meta: dict[str, str]) -> dict[str, pd.Timestamp]:
    index_path = web_data_root / meta["收集表ID"] / "index.json"
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


def build_invalid_suffix_summary(stat: dict[str, Any]) -> dict[str, Any]:
    by_class: dict[str, list[str]] = {}
    for class_name, class_stat in stat.get("班级统计", {}).items():
        invalid = sorted(set(class_stat.get("后缀格式无效名单", [])))
        if invalid:
            by_class[class_name] = invalid
    other = sorted(set(stat.get("其他后缀格式无效名单", [])))
    if other:
        by_class["其他"] = other
    total = sum(len(items) for items in by_class.values())
    return {"总人数": total, "班级统计": by_class}


def is_makeup_window_mode(publish_mode: str) -> bool:
    return publish_mode == "makeup-window"


def publication_mode_text(publish_mode: str) -> str:
    if publish_mode == "cutoff":
        return "截止模式"
    if publish_mode == "makeup-window":
        return "补交窗口模式"
    raise ValueError(f"未知发布模式: {publish_mode}")


def entry_after_cutoff(entry: dict[str, Any] | None, cutoff: pd.Timestamp | None) -> bool:
    if entry is None or cutoff is None:
        return False
    ts = parse_datetime_text(entry.get("提交时间"))
    return bool(ts is not None and ts > cutoff)


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
    publish_mode: str = "cutoff",
    makeup_window_start: pd.Timestamp | None = None,
    makeup_window_end: pd.Timestamp | None = None,
) -> dict[str, Any]:
    allow_makeup = is_makeup_window_mode(publish_mode)
    if allow_makeup:
        if makeup_window_end is None:
            raise ValueError("补交窗口模式必须提供补交窗口结束时间。")
        effective_start = makeup_window_start or cutoff
        if effective_start is not None and makeup_window_end <= effective_start:
            raise ValueError("补交窗口结束时间必须晚于补交窗口开始时间。")
    else:
        makeup_window_start = None
        makeup_window_end = None

    df_submission = df[df["_submission_label"] == submission_label]
    if cutoff is not None:
        df_submission = df_submission[df_submission["_record_time"] <= cutoff]
    latest_record_time = format_datetime(df_submission["_record_time"].max()) if not df_submission.empty else ""

    content_stats: dict[str, Any] = {}
    stat: dict[str, Any] = {
        "收集表ID": meta["收集表ID"],
        "标题": meta["标题"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "状态": meta.get("状态", "active"),
        "提交序号": submission_label,
        "提交内容列表": content_labels,
        "最后提交时间": "",
        "统计截止时间": format_datetime(cutoff) if cutoff is not None else "",
        "发布模式": publication_mode_text(publish_mode),
        "允许补交": allow_makeup,
        "补交窗口开始时间": format_datetime(makeup_window_start or cutoff) if allow_makeup else "",
        "补交窗口结束时间": format_datetime(makeup_window_end) if allow_makeup else "",
        "最后收集记录时间": latest_record_time,
        "统计生成时间": now_text(),
        "总班级数": len(students_by_class),
        "班级统计": {},
        "补交状态": {},
    }

    valid_submit_times: list[pd.Timestamp] = []
    total_expected = 0
    total_submitted = 0
    total_cutoff_submitted = 0
    total_late_submitted = 0
    total_invalid = 0

    for content_label in content_labels:
        content_stats[content_label] = {"班级统计": {}}

    for class_name, students in students_by_class.items():
        cutoff_complete_students: list[str] = []
        cutoff_not_complete_students: list[str] = []
        final_complete_students: list[str] = []
        final_not_complete_students: list[str] = []
        class_invalid_students: set[str] = set()
        class_late_complete_students: set[str] = set()

        for content_label in content_labels:
            content_cutoff_submitted: list[str] = []
            content_cutoff_not_submitted: list[str] = []
            content_final_submitted: list[str] = []
            content_final_not_submitted: list[str] = []
            content_invalid: list[str] = []
            content_late_submitted: list[str] = []
            for student in students:
                cutoff_entry = active_entry_for(manifest, student["学号"], submission_label, content_label, cutoff)
                final_entry = accepted_entry_for(
                    manifest,
                    student["学号"],
                    submission_label,
                    content_label,
                    cutoff,
                    makeup_window_start,
                    makeup_window_end,
                )
                cutoff_active = bool(cutoff_entry and cutoff_entry.get("状态") == "active")
                final_active = bool(final_entry and final_entry.get("状态") == "active")
                final_invalid = bool(
                    not final_active
                    and (
                        (final_entry and final_entry.get("状态") == "invalid")
                        or (cutoff_entry and cutoff_entry.get("状态") == "invalid")
                    )
                )

                if cutoff_active:
                    content_cutoff_submitted.append(student["学号"])
                else:
                    content_cutoff_not_submitted.append(student["学号"])

                if final_active:
                    content_final_submitted.append(student["学号"])
                    if allow_makeup and entry_after_cutoff(final_entry, cutoff):
                        content_late_submitted.append(student["学号"])
                    entry = final_entry
                    ts = parse_datetime_text(entry.get("提交时间"))
                    if ts is not None:
                        valid_submit_times.append(ts)
                else:
                    content_final_not_submitted.append(student["学号"])
                    if final_invalid:
                        content_invalid.append(student["学号"])
                        class_invalid_students.add(student["学号"])
            content_stats[content_label]["班级统计"][class_name] = {
                "应交人数": len(students),
                "截止已交人数": len(content_cutoff_submitted),
                "截止未达标人数": len(content_cutoff_not_submitted),
                "截止提交率": round((len(content_cutoff_submitted) / len(students)) if students else 0, 4),
                "截止已交名单": sorted(content_cutoff_submitted),
                "截止未达标名单": sorted(content_cutoff_not_submitted),
                "已交人数": len(content_final_submitted),
                "未交人数": len(content_final_not_submitted),
                "提交率": round((len(content_final_submitted) / len(students)) if students else 0, 4),
                "已交名单": sorted(content_final_submitted),
                "未交名单": sorted(content_final_not_submitted),
                "后缀格式无效人数": len(content_invalid),
                "后缀格式无效名单": sorted(content_invalid),
                "已补交人数": len(content_late_submitted),
                "已补交名单": sorted(content_late_submitted),
            }

        for student in students:
            cutoff_entries = [
                active_entry_for(manifest, student["学号"], submission_label, content_label, cutoff)
                for content_label in content_labels
            ]
            final_entries = [
                accepted_entry_for(
                    manifest,
                    student["学号"],
                    submission_label,
                    content_label,
                    cutoff,
                    makeup_window_start,
                    makeup_window_end,
                )
                for content_label in content_labels
            ]
            cutoff_complete = bool(cutoff_entries and all(entry and entry.get("状态") == "active" for entry in cutoff_entries))
            final_complete = bool(final_entries and all(entry and entry.get("状态") == "active" for entry in final_entries))
            final_invalid = bool(
                not final_complete
                and (
                    any(entry and entry.get("状态") == "invalid" for entry in final_entries)
                    or any(entry and entry.get("状态") == "invalid" for entry in cutoff_entries)
                )
            )

            if cutoff_complete:
                cutoff_complete_students.append(student["学号"])
            else:
                cutoff_not_complete_students.append(student["学号"])

            if final_complete:
                final_complete_students.append(student["学号"])
                if allow_makeup and any(entry_after_cutoff(entry, cutoff) for entry in final_entries):
                    class_late_complete_students.add(student["学号"])
            else:
                final_not_complete_students.append(student["学号"])
                if final_invalid:
                    class_invalid_students.add(student["学号"])

        expected_count = len(students)
        cutoff_submitted_count = len(cutoff_complete_students)
        late_submitted_count = len(class_late_complete_students)
        submitted_count = len(final_complete_students)
        total_expected += expected_count
        total_submitted += submitted_count
        total_cutoff_submitted += cutoff_submitted_count
        total_late_submitted += late_submitted_count
        total_invalid += len(class_invalid_students)
        stat["班级统计"][class_name] = {
            "应交人数": expected_count,
            "截止已交人数": cutoff_submitted_count,
            "截止未达标人数": expected_count - cutoff_submitted_count,
            "截止提交率": round((cutoff_submitted_count / expected_count) if expected_count else 0, 4),
            "截止已交名单": sorted(cutoff_complete_students),
            "截止未达标名单": sorted(cutoff_not_complete_students),
            "已交人数": submitted_count,
            "未交人数": expected_count - submitted_count,
            "提交率": round((submitted_count / expected_count) if expected_count else 0, 4),
            "已交名单": sorted(final_complete_students),
            "未交名单": sorted(final_not_complete_students),
            "后缀格式无效人数": len(class_invalid_students),
            "后缀格式无效名单": sorted(class_invalid_students),
            "已补交人数": late_submitted_count,
            "已补交名单": sorted(class_late_complete_students),
        }
        stat["补交状态"][class_name] = {
            "已补交名单": sorted(class_late_complete_students),
        }

    other_submitted: list[str] = []
    other_invalid: set[str] = set()
    other_late_submitted: list[str] = []
    for student in other_students_by_name.values():
        cutoff_entries = [
            active_entry_for(manifest, student["学号"], submission_label, content_label, cutoff)
            for content_label in content_labels
        ]
        final_entries = [
            accepted_entry_for(
                manifest,
                student["学号"],
                submission_label,
                content_label,
                cutoff,
                makeup_window_start,
                makeup_window_end,
            )
            for content_label in content_labels
        ]
        cutoff_complete = bool(cutoff_entries and all(entry and entry.get("状态") == "active" for entry in cutoff_entries))
        final_complete = bool(final_entries and all(entry and entry.get("状态") == "active" for entry in final_entries))
        if final_complete:
            if allow_makeup and any(entry_after_cutoff(entry, cutoff) for entry in final_entries):
                other_late_submitted.append(student["学号"])
            else:
                other_submitted.append(student["学号"])
            for entry in final_entries:
                ts = parse_datetime_text(entry.get("提交时间")) if entry else None
                if ts is not None:
                    valid_submit_times.append(ts)
        else:
            for entry in final_entries + cutoff_entries:
                if not entry:
                    continue
                if entry.get("状态") == "invalid":
                    other_invalid.add(student["学号"])

    if valid_submit_times:
        stat["最后提交时间"] = format_datetime(max(valid_submit_times))
    stat["其他已交名单"] = sorted(other_submitted)
    stat["其他后缀格式无效名单"] = sorted(other_invalid)
    stat["其他已补交名单"] = sorted(other_late_submitted)
    stat["汇总"] = {
        "应交总人数": total_expected,
        "截止已交总人数": total_cutoff_submitted,
        "已补交总人数": total_late_submitted,
        "已交总人数": total_submitted,
        "未交总人数": total_expected - total_submitted,
        "总提交率": round((total_submitted / total_expected) if total_expected else 0, 4),
        "后缀格式无效总人数": total_invalid + len(other_invalid),
    }
    stat["提交内容统计"] = content_stats
    stat["后缀格式无效"] = build_invalid_suffix_summary(stat)
    return stat
