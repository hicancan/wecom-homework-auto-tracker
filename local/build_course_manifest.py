from __future__ import annotations

import argparse
from pathlib import Path

from course_manifest import rebuild_course_manifest


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    parser = argparse.ArgumentParser(description="生成前端收集表 manifest 与哈希 JSON 资源。")
    parser.add_argument(
        "--public-root",
        default=str(repo_root / "webapp" / "public"),
        help="webapp public 目录",
    )
    parser.add_argument(
        "--collection-index",
        default=str(repo_root / "webapp" / "public" / "collections.json"),
        help="稳定收集表索引文件路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = rebuild_course_manifest(
        public_root=Path(args.public_root),
        course_index_path=Path(args.collection_index),
    )
    print(f"manifest: {result['manifest_file']}")
    print(f"index: {result['index_file']}")
    print(f"version: {result['version']}")


if __name__ == "__main__":
    main()
