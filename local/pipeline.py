from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from archive import merge_incremental_archive
from attachments import build_attachment_lookup, find_attachments_dir
from cleanup import execute_source_attachment_cleanup
from contract import (
    dump_json,
    now_text,
    parse_datetime_text,
    resolve_path,
    sort_submission_key,
)
from excel_loader import load_collection_excel
from stats import load_existing_submission_cutoffs, make_submission_stat, resolve_submission_cutoffs
from students import load_students, resolve_target_classes, scope_students_by_classes
from web_publish import write_collection_web_data
from zip_writer import create_submission_zip, write_submission_reports


def extract_student_id_from_filename(filename: str) -> str:
    if not filename:
        return ""
    match = re.search(r"[A-Z]\d{8}", str(filename))
    return match.group(0) if match else ""


def count_archive_status(manifest: dict[str, Any]) -> dict[str, int]:
    active = 0
    source_unavailable = 0
    invalid = 0
    for entry in manifest.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        versions = entry.get("versions", [])
        if not versions:
            continue
        status_rank = {"active": 0, "invalid": 1, "missing": 2}
        versions = sorted(
            versions,
            key=lambda version: (
                -int(parse_datetime_text(version.get("提交时间")).timestamp())
                if parse_datetime_text(version.get("提交时间"))
                else 0,
                status_rank.get(version.get("状态", ""), 99),
            ),
        )
        status = str(versions[0].get("状态") or versions[0].get("status", "")).strip()
        if status == "active":
            active += 1
        elif status == "missing":
            source_unavailable += 1
        elif status == "invalid":
            invalid += 1
    return {"active": active, "source_unavailable": source_unavailable, "invalid": invalid}


def check_unknown_students(
    df: pd.DataFrame,
    students_by_name: dict[str, dict[str, str]],
    other_students_by_name: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    all_names = set(students_by_name) | set(other_students_by_name)
    unknown_names = sorted(set(df["_name_norm"].unique()) - all_names)
    if not unknown_names:
        return []

    report: list[dict[str, Any]] = []
    for name in unknown_names:
        rows = df[df["_name_norm"] == name]
        filenames = rows["_uploaded_filename"].dropna().astype(str).unique().tolist()
        ids = list(dict.fromkeys(sid for fn in filenames if (sid := extract_student_id_from_filename(fn))))
        report.append({
            "姓名": name,
            "推测学号": ids[0] if len(ids) == 1 else (ids if ids else "未检测到"),
            "提交序号": sorted(set(rows["_submission_label"].tolist())),
            "提交内容": sorted(set(rows["_content_label"].tolist())),
            "记录数": int(len(rows)),
        })
    return report


def format_unknown_report(report: list[dict[str, Any]]) -> str:
    lines = [
        f"\n{'=' * 60}",
        f"  [ERROR] 发现 {len(report)} 位不在学生名单中的填写人",
        f"{'=' * 60}",
    ]
    for item in report:
        ids = item["推测学号"]
        if isinstance(ids, list):
            ids = ", ".join(ids)
        lines.append(f"\n  姓名: {item['姓名']}")
        lines.append(f"  推测学号: {ids}")
        lines.append(f"  提交序号: {', '.join(item['提交序号'])}")
        lines.append(f"  提交内容: {', '.join(item['提交内容'])}")
        lines.append(f"  记录数: {item['记录数']}")
    lines.append("\n  解决方法:")
    lines.append("    1. 将学生加入 config/other_students.json")
    lines.append("    2. 或使用 --skip-unknown 跳过未知学生继续收集")
    lines.append(f"{'=' * 60}\n")
    return "\n".join(lines)


def process_collection(
    *,
    collection_id: str,
    excel_path: Path,
    cfg: dict[str, Any],
    repo_root: Path,
    requested_labels: list[str],
    attachments_override: str,
    cutoff_policy: str,
    manual_cutoffs: dict[str, pd.Timestamp],
    cleanup_mode: str,
    cleanup_only: bool,
    skip_unknown: bool,
    publish_mode: str,
    makeup_window_start: pd.Timestamp | None,
    makeup_window_end: pd.Timestamp | None,
    configured_meta: dict[str, Any],
) -> dict[str, Any]:
    df, parsed_meta, columns = load_collection_excel(excel_path)
    meta = {
        "收集表ID": collection_id,
        "标题": configured_meta["标题"],
        "主题": parsed_meta["主题"],
        "对象": parsed_meta["对象"],
        "周期": parsed_meta["周期"],
        "状态": configured_meta["状态"],
    }
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
    configured_classes = configured_meta.get("classes", [])
    if configured_classes:
        target_classes = [str(item).strip() for item in configured_classes if str(item).strip()]
    else:
        target_classes = resolve_target_classes(meta, df, students_by_name)
    students_by_class = scope_students_by_classes(students_by_class_all, target_classes)

    unknown_report = check_unknown_students(df, students_by_name, other_students_by_name)
    if unknown_report:
        report_text = format_unknown_report(unknown_report)
        if not skip_unknown:
            print(report_text)
            raise SystemExit(1)
        print(report_text)
        print("  [WARN] --skip-unknown 已启用，跳过以上学生继续收集...\n")

    attachments_root = resolve_path(cfg.get("attachments_root", ""), repo_root)
    attachments_dir = find_attachments_dir(meta["标题"], attachments_root, attachments_override)
    attachment_lookup, duplicate_lookup = build_attachment_lookup(attachments_dir)

    out_root = resolve_path(cfg.get("out_root", "out"), repo_root)
    web_data_root = resolve_path(cfg.get("web_data_root", "webapp/public/data"), repo_root)
    collection_index_path = resolve_path(cfg.get("collection_index", "webapp/public/collections.json"), repo_root)
    collection_out_dir = out_root / "collections" / collection_id
    collection_out_dir.mkdir(parents=True, exist_ok=True)
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
            collection_out_dir=collection_out_dir,
            mode=cleanup_mode,
        )
        return {"收集表ID": collection_id, "标题": meta["标题"], "清理报告": str(report_path)}

    manifest = merge_incremental_archive(
        df=df,
        columns=columns,
        meta=meta,
        selected_labels=selected_labels,
        collection_out_dir=collection_out_dir,
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
        content_labels = sorted(dict.fromkeys(label_rows["_content_label"].tolist()))
        label_makeup_start = makeup_window_start or cutoff
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
            publish_mode=publish_mode,
            makeup_window_start=label_makeup_start if publish_mode == "makeup-window" else None,
            makeup_window_end=makeup_window_end if publish_mode == "makeup-window" else None,
        )
        stats[label] = stat
        write_submission_reports(collection_out_dir, label, stat)
        zip_paths.append(
            str(
                create_submission_zip(
                    collection_out_dir,
                    label,
                    manifest,
                    cutoff,
                    label_makeup_start if publish_mode == "makeup-window" else None,
                    makeup_window_end if publish_mode == "makeup-window" else None,
                )
            )
        )

    archive_counts = count_archive_status(manifest)
    print(
        "\n  归档状态: "
        f"active={archive_counts['active']} "
        f"source_unavailable={archive_counts['source_unavailable']} "
        f"invalid={archive_counts['invalid']}"
    )

    summary = {
        "收集表ID": collection_id,
        "标题": meta["标题"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "状态": meta["状态"],
        "更新时间": now_text(),
        "提交序号列表": selected_labels,
        "统计文件目录": str(collection_out_dir / "stats"),
        "压缩包列表": zip_paths,
        "发布模式": "补交窗口模式" if publish_mode == "makeup-window" else "截止模式",
        "归档统计": archive_counts,
    }
    (collection_out_dir / "collection_summary.json").write_text(dump_json(summary), encoding="utf-8")

    if cleanup_mode != "off":
        summary["源附件清理报告"] = str(
            execute_source_attachment_cleanup(
                df=df,
                selected_labels=selected_labels,
                attachments_dir=attachments_dir,
                attachment_lookup=attachment_lookup,
                duplicate_lookup=duplicate_lookup,
                collection_out_dir=collection_out_dir,
                mode=cleanup_mode,
            )
        )
        (collection_out_dir / "collection_summary.json").write_text(dump_json(summary), encoding="utf-8")

    write_collection_web_data(
        web_data_root=web_data_root,
        collection_index_path=collection_index_path,
        meta=meta,
        submission_stats=stats,
        selected_labels=selected_labels,
        all_labels=all_labels,
    )
    return summary
