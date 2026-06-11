from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def default_deploy_time() -> str:
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON 文件不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return data


def write_json_object(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stamp_deploy_time(public_root: Path, collection_index_path: Path, deploy_time: str | None = None) -> str:
    public_root = public_root.resolve()
    collection_index_path = collection_index_path.resolve()
    deploy_time = deploy_time or default_deploy_time()

    index_data = read_json_object(collection_index_path)
    collection_refs = index_data.get("收集表列表")
    if not isinstance(collection_refs, list):
        raise ValueError(f"收集表索引缺少数组字段 `收集表列表`: {collection_index_path}")

    index_data["最后部署时间"] = deploy_time
    write_json_object(collection_index_path, index_data)

    for item in collection_refs:
        if not isinstance(item, dict):
            raise ValueError(f"收集表索引项必须是对象: {collection_index_path}")
        rel = str(item.get("数据文件", "")).strip()
        if not rel:
            raise ValueError(f"收集表索引项缺少数据文件: {collection_index_path}")
        collection_path = (public_root / rel).resolve()
        if not collection_path.exists():
            raise FileNotFoundError(f"收集表索引文件不存在: {collection_path}")
        collection_data = read_json_object(collection_path)
        submission_refs = collection_data.get("提交序号列表")
        if not isinstance(submission_refs, list):
            raise ValueError(f"收集表索引缺少数组字段 `提交序号列表`: {collection_path}")

        collection_data["最后部署时间"] = deploy_time
        write_json_object(collection_path, collection_data)

        for submission in submission_refs:
            if not isinstance(submission, dict):
                raise ValueError(f"提交序号索引项必须是对象: {collection_path}")
            submission_rel = str(submission.get("数据文件", "")).strip()
            if not submission_rel:
                raise ValueError(f"提交序号索引项缺少数据文件: {collection_path}")
            submission_path = (public_root / submission_rel).resolve()
            if not submission_path.exists():
                raise FileNotFoundError(f"提交序号数据文件不存在: {submission_path}")
            submission_data = read_json_object(submission_path)
            submission_data["最后部署时间"] = deploy_time
            write_json_object(submission_path, submission_data)

    return deploy_time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="给公开收集表 JSON 写入部署时间。")
    parser.add_argument("--public-root", default="webapp/public")
    parser.add_argument("--collection-index", default="webapp/public/collections.json")
    parser.add_argument("--deploy-time", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    deploy_time = stamp_deploy_time(
        public_root=Path(args.public_root),
        collection_index_path=Path(args.collection_index),
        deploy_time=args.deploy_time or None,
    )
    print(f"Stamped deploy time: {deploy_time}")


if __name__ == "__main__":
    main()
