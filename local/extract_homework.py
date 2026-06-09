from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pandas as pd

from archive import merge_incremental_archive
from attachments import build_attachment_lookup, find_attachments_dir
from cleanup import execute_source_attachment_cleanup
from contract import (
    dump_json,
    load_local_config,
    normalize_text,
    now_text,
    parse_collection_title,
    parse_datetime_text,
    require_collection_id,
    resolve_path,
    sort_submission_key,
)
from excel_loader import discover_collection_excels, load_collection_excel
from stats import load_existing_submission_cutoffs, make_submission_stat, resolve_submission_cutoffs
from students import load_students, resolve_target_classes, scope_students_by_classes
from web_publish import write_collection_web_data
from zip_writer import create_submission_zip, write_submission_reports


def collection_registry(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = cfg.get("collections")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("配置缺少 collections；每个收集表必须显式配置稳定 collection_id。")
    registry: dict[str, dict[str, Any]] = {}
    for collection_id, item in raw.items():
        if not isinstance(item, dict):
            raise ValueError(f"collections.{collection_id} 必须是对象。")
        cid = require_collection_id(str(collection_id))
        title = str(item.get("title", "")).strip()
        if not title:
            raise ValueError(f"collections.{cid}.title 不能为空。")
        meta = parse_collection_title(title)
        registry[cid] = {
            "收集表ID": cid,
            "标题": title,
            "主题": meta["主题"],
            "对象": meta["对象"],
            "周期": meta["周期"],
            "状态": str(item.get("status", "active")).strip() or "active",
            "classes": item.get("classes", []),
            "excel": str(item.get("excel", "")).strip(),
        }
    return registry


def meta_for_excel(excel_path: Path, registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    title = excel_path.stem
    matches = [item for item in registry.values() if item["标题"] == title]
    if len(matches) != 1:
        raise ValueError(f"收集表标题未唯一绑定 collection_id: {title}")
    return matches[0]


def configured_excels(repo_root: Path, cfg: dict[str, Any], registry: dict[str, dict[str, Any]]) -> dict[str, Path]:
    courses_dir = resolve_path(cfg.get("courses_dir", "config"), repo_root)
    discovered = discover_collection_excels(courses_dir)
    result: dict[str, Path] = {}
    for collection_id, item in registry.items():
        excel_text = str(item.get("excel", "")).strip()
        if not excel_text:
            continue
        excel_path = resolve_path(excel_text, repo_root)
        if not excel_path.exists():
            raise FileNotFoundError(f"收集表 Excel 不存在: {collection_id} -> {excel_path}")
        if excel_path.stem not in discovered:
            raise ValueError(f"Excel 标题不符合新模型或不在 courses_dir 中: {excel_path.name}")
        result[collection_id] = excel_path
    return result


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


def pick_excel(args: argparse.Namespace, repo_root: Path, cfg: dict[str, Any]) -> tuple[str, Path, dict[str, Any]]:
    registry = collection_registry(cfg)
    excels = configured_excels(repo_root, cfg, registry)
    if args.list_collections:
        for collection_id, path in excels.items():
            print(f"{collection_id}\t{registry[collection_id]['标题']}\t{path}")
        raise SystemExit(0)
    if args.excel:
        path = Path(args.excel).expanduser()
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Excel 不存在: {path}")
        meta = meta_for_excel(path, registry)
        return meta["收集表ID"], path, meta
    if args.collection_id:
        if args.collection_id not in excels:
            raise ValueError(f"收集表不存在或没有 Excel: {args.collection_id}")
        return args.collection_id, excels[args.collection_id], registry[args.collection_id]
    if len(excels) == 1:
        collection_id = next(iter(excels))
        return collection_id, excels[collection_id], registry[collection_id]
    raise ValueError("检测到多份新模型 Excel，请使用 --collection-id 或 --excel 指定。")


def _extract_student_id_from_filename(filename: str) -> str:
    """Try to extract a student ID (e.g. B23110622) from an uploaded filename."""
    if not filename:
        return ""
    match = re.search(r"[A-Z]\d{8}", str(filename))
    return match.group(0) if match else ""


def _count_archive_status(manifest: dict[str, Any]) -> dict[str, int]:
    active = 0
    missing = 0
    invalid = 0
    for entry in manifest.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        versions = entry.get("versions", [])
        if not versions:
            continue
        latest = versions[-1]
        status = str(latest.get("状态") or latest.get("status", "")).strip()
        if status == "active":
            active += 1
        elif status == "missing":
            missing += 1
        elif status == "invalid":
            invalid += 1
    return {"active": active, "missing": missing, "invalid": invalid}


def check_unknown_students(
    df: pd.DataFrame,
    students_by_name: dict[str, dict[str, str]],
    other_students_by_name: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    all_names = set(students_by_name) | set(other_students_by_name)
    df_known = df[df["_name_norm"].isin(all_names)]
    unknown_names = sorted(set(df["_name_norm"].unique()) - all_names)
    if not unknown_names:
        return []

    report: list[dict[str, Any]] = []
    for name in unknown_names:
        rows = df[df["_name_norm"] == name]
        filenames = rows["_uploaded_filename"].dropna().astype(str).unique().tolist()
        ids = list(dict.fromkeys(
            sid for fn in filenames if (sid := _extract_student_id_from_filename(fn))
        ))
        report.append({
            "姓名": name,
            "推测学号": ids[0] if len(ids) == 1 else (ids if ids else "未检测到"),
            "提交序号": sorted(set(rows["_submission_label"].tolist())),
            "提交内容": sorted(set(rows["_content_label"].tolist())),
            "记录数": int(len(rows)),
        })
    return report


def _format_unknown_report(report: list[dict[str, Any]]) -> str:
    lines = [
        f"\n{'='*60}",
        f"  [ERROR] 发现 {len(report)} 位不在学生名单中的填写人",
        f"{'='*60}",
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
    lines.append(f"\n  解决方法:")
    lines.append(f"    1. 将学生加入 config/other_students.json")
    lines.append(f"    2. 或使用 --skip-unknown 跳过未知学生继续收集")
    lines.append(f"{'='*60}\n")
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
    no_late: bool,
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

    # ---- FAIL-FAST: check for unknown students BEFORE any processing ----
    unknown_report = check_unknown_students(df, students_by_name, other_students_by_name)
    if unknown_report:
        report_text = _format_unknown_report(unknown_report)
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
            course_out_dir=collection_out_dir,
            mode=cleanup_mode,
        )
        return {"收集表ID": collection_id, "标题": meta["标题"], "清理报告": str(report_path)}

    manifest = merge_incremental_archive(
        df=df,
        columns=columns,
        meta=meta,
        selected_labels=selected_labels,
        course_out_dir=collection_out_dir,
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
            no_late=no_late,
        )
        stats[label] = stat
        write_submission_reports(collection_out_dir, label, stat)
        zip_cutoff = cutoff if no_late else None
        zip_paths.append(str(create_submission_zip(collection_out_dir, label, manifest, zip_cutoff)))

    archive_counts = _count_archive_status(manifest)
    print(f"\n  归档状态: active={archive_counts['active']} missing={archive_counts['missing']} invalid={archive_counts['invalid']}")

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
                course_out_dir=collection_out_dir,
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


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    parser = argparse.ArgumentParser(description="新模型增量收集: 标题[对象][周期] + 提交序号 + 提交内容 + 文件")
    parser.add_argument("--config", default=str(repo_root / "config" / "config.json"))
    parser.add_argument("--excel", default="", help="指定新模型 Excel")
    parser.add_argument("--collection-id", default="", help="按稳定收集表 ID 选择 config.collections 中的 Excel")
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
        help="按选中提交序号清理企业微信同步源文件，默认不清理",
    )
    parser.add_argument("--cleanup-only", action="store_true", help="仅执行源文件清理，不更新归档和 web 数据")
    parser.add_argument("--skip-unknown", action="store_true", help="跳过不在名单中的填写人，不触发 fail-fast")
    parser.add_argument("--no-late", action="store_true", help="不允许补交：ZIP 只打包截止内文件，补交计入未交")
    parser.add_argument("--list-collections", action="store_true")
    parser.add_argument("--list-submission-labels", action="store_true")
    return parser.parse_args()


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    args = parse_args()
    config_path = resolve_path(args.config, repo_root)
    if not config_path.exists():
        fallback = repo_root / "config" / "local.config.json"
        config_path = fallback if fallback.exists() else config_path
    cfg = load_local_config(config_path)
    collection_id, excel_path, configured_meta = pick_excel(args, repo_root, cfg)
    df, _, _ = load_collection_excel(excel_path)
    labels = sorted(dict.fromkeys(df["_submission_label"].tolist()), key=sort_submission_key)
    if args.list_submission_labels:
        print(f">>> {collection_id} | {configured_meta['标题']}")
        for idx, label in enumerate(labels, 1):
            contents = sorted(dict.fromkeys(df[df["_submission_label"] == label]["_content_label"].tolist()))
            print(f"{idx}. {label} | {', '.join(contents)}")
        return

    requested_labels = ["__ALL__"] if args.all_labels else [normalize_text(label) for label in args.labels]
    summary = process_collection(
        collection_id=collection_id,
        excel_path=excel_path,
        cfg=cfg,
        repo_root=repo_root,
        requested_labels=requested_labels,
        attachments_override=args.attachments,
        cutoff_policy=args.cutoff_policy,
        manual_cutoffs=parse_manual_cutoffs(args.cutoff),
        cleanup_mode=args.cleanup_source_attachments,
        cleanup_only=args.cleanup_only,
        skip_unknown=args.skip_unknown,
        no_late=args.no_late,
        configured_meta=configured_meta,
    )
    print("处理完成:")
    print(dump_json(summary))


if __name__ == "__main__":
    main()
