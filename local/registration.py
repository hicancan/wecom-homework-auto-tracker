from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from contract import normalize_text, require_collection_id, resolve_path, suggest_collection_id
from excel_loader import discover_collection_excels, load_collection_excel
from students import expand_class_audience


@dataclass(frozen=True)
class UnregisteredCollection:
    suggested_collection_id: str
    title: str
    excel: Path
    classes: list[str]
    labels: dict[str, list[str]]


def relative_config_path(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def labels_from_loaded_df(df: pd.DataFrame) -> dict[str, list[str]]:
    labels: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        label = normalize_text(row["_submission_label"])
        content = normalize_text(row["_content_label"])
        if not label or not content:
            raise ValueError("提交序号/提交内容不能为空")
        labels.setdefault(label, [])
        if content not in labels[label]:
            labels[label].append(content)
    return labels


def discover_unregistered_excels(repo_root: Path, cfg: dict) -> list[UnregisteredCollection]:
    collections_dir = resolve_path(cfg.get("collections_dir", "config"), repo_root)
    discovered = discover_collection_excels(collections_dir)
    raw = cfg.get("collections")
    registered_titles: set[str] = set()
    existing_ids: set[str] = set()
    if isinstance(raw, dict):
        for collection_id, item in raw.items():
            existing_ids.add(require_collection_id(str(collection_id)))
            if isinstance(item, dict):
                title = normalize_text(item.get("title"))
                if title:
                    registered_titles.add(title)

    candidates: list[UnregisteredCollection] = []
    for title, excel in discovered.items():
        if title in registered_titles:
            continue
        df, meta, _ = load_collection_excel(excel)
        suggested_id = suggest_collection_id(title, existing_ids)
        existing_ids.add(suggested_id)
        candidates.append(
            UnregisteredCollection(
                suggested_collection_id=suggested_id,
                title=title,
                excel=excel,
                classes=expand_class_audience(meta["对象"]),
                labels=labels_from_loaded_df(df),
            )
        )
    return candidates


def register_unregistered_excels(repo_root: Path, config_path: Path, cfg: dict) -> dict:
    candidates = discover_unregistered_excels(repo_root, cfg)
    if not candidates:
        return cfg

    print("\n发现未注册的新模型 Excel:")
    for idx, item in enumerate(candidates, 1):
        label_text = "；".join(f"{label}: {', '.join(contents)}" for label, contents in item.labels.items())
        class_text = ", ".join(item.classes) if item.classes else "未从对象解析班级"
        print(f"  {idx}. {item.suggested_collection_id} | {item.title}")
        print(f"     班级: {class_text}")
        print(f"     提交: {label_text}")
    raw = input("是否注册以上 Excel 到 local.config.json？[Y/n]: ").strip().lower()
    if raw in {"n", "no"}:
        return cfg

    collections = cfg.setdefault("collections", {})
    if not isinstance(collections, dict):
        raise ValueError("配置 collections 必须是对象。")
    for item in candidates:
        collection_id = input(f"{item.title} 的 collection_id（默认 {item.suggested_collection_id}）: ").strip()
        collection_id = require_collection_id(collection_id or item.suggested_collection_id)
        if collection_id in collections:
            raise ValueError(f"collection_id 已存在: {collection_id}")
        classes = item.classes
        if not classes:
            raw_classes = input(f"{item.title} 班级列表（逗号分隔）: ").strip()
            classes = [part.strip() for part in raw_classes.replace("，", ",").split(",") if part.strip()]
            if not classes:
                raise ValueError(f"无法注册未指定班级的收集表: {item.title}")
        collections[collection_id] = {
            "title": item.title,
            "status": "active",
            "classes": classes,
            "excel": relative_config_path(repo_root, item.excel),
        }

    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已更新本地配置: {config_path}")
    return cfg
