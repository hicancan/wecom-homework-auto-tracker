from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contract import build_path_tokens, dump_json, now_text, sort_submission_key
from course_manifest import rebuild_course_manifest


def read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 必须是对象: {path}")
    return data


def rebuild_collection_index_from_data(web_data_root: Path, collection_index_path: Path) -> None:
    items: list[dict[str, Any]] = []
    for index_file in sorted(web_data_root.glob("*/index.json")):
        data = read_json_object(index_file)
        collection_id = str(data.get("收集表ID", "")).strip()
        title = str(data.get("标题", "")).strip()
        if not collection_id or not title:
            continue
        items.append(
            {
                "收集表ID": collection_id,
                "数据文件": f"data/{collection_id}/index.json",
                "标题": title,
                "主题": str(data.get("主题", title)).strip(),
                "对象": str(data.get("对象", "")).strip(),
                "周期": str(data.get("周期", "")).strip(),
                "状态": str(data.get("状态", "active")).strip() or "active",
            }
        )
    items.sort(key=lambda item: (item.get("周期") or "未分组", item["状态"] == "archived", item["主题"]))
    collection_index_path.parent.mkdir(parents=True, exist_ok=True)
    collection_index_path.write_text(
        dump_json({"更新时间": now_text(), "收集表列表": items}),
        encoding="utf-8",
    )


def write_collection_web_data(
    *,
    web_data_root: Path,
    collection_index_path: Path,
    meta: dict[str, str],
    submission_stats: dict[str, dict[str, Any]],
    selected_labels: list[str],
    all_labels: list[str],
) -> None:
    collection_id = meta["收集表ID"]
    collection_dir = web_data_root / collection_id
    collection_dir.mkdir(parents=True, exist_ok=True)
    index_path = collection_dir / "index.json"
    existing_refs: dict[str, dict[str, Any]] = {}
    if index_path.exists():
        existing_index = read_json_object(index_path)
        refs = existing_index.get("提交序号列表", [])
        if not isinstance(refs, list):
            raise ValueError(f"收集表索引提交序号列表无效: {index_path}")
        for item in refs:
            if not isinstance(item, dict):
                continue
            label = str(item.get("提交序号", "")).strip()
            if label:
                existing_refs[label] = item

    full_refresh = set(selected_labels) == set(all_labels)
    if full_refresh:
        final_labels = all_labels
        existing_refs = {label: ref for label, ref in existing_refs.items() if label in set(all_labels)}
    else:
        final_labels = sorted(set(existing_refs) | set(selected_labels), key=sort_submission_key)

    tokens = build_path_tokens(final_labels)
    keep_files = {"index.json"}

    for label in selected_labels:
        stat = submission_stats.get(label)
        if stat is None:
            continue
        token = tokens[label]
        filename = f"{token}.json"
        keep_files.add(filename)
        payload = dict(stat)
        payload["提交序号ID"] = token
        payload["更新时间"] = now_text()
        (collection_dir / filename).write_text(dump_json(payload), encoding="utf-8")
        existing_refs[label] = {
            "提交序号ID": token,
            "提交序号": label,
            "数据文件": f"data/{collection_id}/{filename}",
            "提交内容列表": stat.get("提交内容列表", []),
        }

    submission_refs = [existing_refs[label] for label in final_labels if label in existing_refs]
    for item in submission_refs:
        data_file = str(item.get("数据文件", "")).strip()
        prefix = f"data/{collection_id}/"
        if data_file.startswith(prefix):
            keep_files.add(data_file.removeprefix(prefix))

    index_payload = {
        "收集表ID": collection_id,
        "标题": meta["标题"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "状态": meta.get("状态", "active"),
        "更新时间": now_text(),
        "提交序号列表": submission_refs,
    }
    index_path.write_text(dump_json(index_payload), encoding="utf-8")

    if full_refresh:
        for stale in collection_dir.glob("*.json"):
            if stale.name not in keep_files:
                stale.unlink()

    rebuild_collection_index_from_data(web_data_root, collection_index_path)
    rebuild_course_manifest(public_root=collection_index_path.parent, course_index_path=collection_index_path)
