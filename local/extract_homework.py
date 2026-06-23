from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from contract import (
    dump_json,
    load_local_config,
    normalize_text,
    parse_collection_title,
    parse_datetime_text,
    require_collection_id,
    resolve_path,
    sort_submission_key,
)
from excel_loader import discover_collection_excels, load_collection_excel
from pipeline import process_collection


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
            "default_content": str(item.get("default_content", "")).strip(),
        }
    return registry


def meta_for_excel(excel_path: Path, registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    title = excel_path.stem
    matches = [item for item in registry.values() if item["标题"] == title]
    if len(matches) != 1:
        raise ValueError(f"收集表标题未唯一绑定 collection_id: {title}")
    return matches[0]


def configured_excels(repo_root: Path, cfg: dict[str, Any], registry: dict[str, dict[str, Any]]) -> dict[str, Path]:
    collections_dir_text = str(cfg.get("collections_dir", "")).strip()
    if not collections_dir_text:
        raise ValueError("配置缺少 collections_dir；请显式指定收集表 Excel 所在目录。")
    collections_dir = resolve_path(collections_dir_text, repo_root)
    discovered = discover_collection_excels(collections_dir)
    result: dict[str, Path] = {}
    for collection_id, item in registry.items():
        excel_text = str(item.get("excel", "")).strip()
        if not excel_text:
            continue
        excel_path = resolve_path(excel_text, repo_root)
        if not excel_path.exists():
            raise FileNotFoundError(f"收集表 Excel 不存在: {collection_id} -> {excel_path}")
        if excel_path.stem not in discovered:
            raise ValueError(f"Excel 标题不符合新模型或不在 collections_dir 中: {excel_path.name}")
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


def parse_cli_datetime(value: str, option_name: str) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = parse_datetime_text(text)
    if parsed is None:
        raise ValueError(f"{option_name} 时间无效: {value}")
    return parsed


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
    parser.add_argument("--zip-to-desktop", action="store_true", help="将生成的 ZIP 文件复制到桌面")
    parser.add_argument(
        "--publish-mode",
        choices=["cutoff", "makeup-window"],
        default="cutoff",
        help="发布模式：cutoff 只发布截止内统计和 ZIP；makeup-window 发布截止内 + 补交窗口内统计和 ZIP",
    )
    parser.add_argument("--makeup-window-start", default="", help="补交窗口开始时间；默认等于各提交序号统计截止时间")
    parser.add_argument("--makeup-window-end", default="", help="补交窗口结束时间，格式 YYYY-MM-DD HH:MM:SS")
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
        zip_to_desktop=args.zip_to_desktop,
        publish_mode=args.publish_mode,
        makeup_window_start=parse_cli_datetime(args.makeup_window_start, "--makeup-window-start"),
        makeup_window_end=parse_cli_datetime(args.makeup_window_end, "--makeup-window-end"),
        configured_meta=configured_meta,
    )
    print("处理完成:")
    print(dump_json(summary))


if __name__ == "__main__":
    main()
