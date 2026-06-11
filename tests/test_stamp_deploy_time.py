from __future__ import annotations

import json
from pathlib import Path

import pytest

from stamp_deploy_time import stamp_deploy_time


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_stamp_deploy_time_updates_index_and_submission_files(tmp_path: Path) -> None:
    public = tmp_path / "public"
    write_json(
        public / "collections.json",
        {
            "收集表列表": [
                {
                    "收集表ID": "demo",
                    "数据文件": "data/demo/index.json",
                }
            ]
        },
    )
    write_json(
        public / "data" / "demo" / "index.json",
        {
            "收集表ID": "demo",
            "提交序号列表": [
                {
                    "提交序号ID": "seq-001",
                    "数据文件": "data/demo/seq-001.json",
                }
            ],
        },
    )
    write_json(public / "data" / "demo" / "seq-001.json", {"收集表ID": "demo"})

    stamped = stamp_deploy_time(public, public / "collections.json", "2026-06-11 23:59:00")

    assert stamped == "2026-06-11 23:59:00"
    for path in [
        public / "collections.json",
        public / "data" / "demo" / "index.json",
        public / "data" / "demo" / "seq-001.json",
    ]:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["最后部署时间"] == "2026-06-11 23:59:00"


def test_stamp_deploy_time_fails_on_missing_submission_file(tmp_path: Path) -> None:
    public = tmp_path / "public"
    write_json(
        public / "collections.json",
        {"收集表列表": [{"收集表ID": "demo", "数据文件": "data/demo/index.json"}]},
    )
    write_json(
        public / "data" / "demo" / "index.json",
        {"提交序号列表": [{"提交序号ID": "seq-001", "数据文件": "data/demo/missing.json"}]},
    )

    with pytest.raises(FileNotFoundError, match="提交序号数据文件不存在"):
        stamp_deploy_time(public, public / "collections.json", "2026-06-11 23:59:00")


def test_stamp_deploy_time_fails_on_invalid_collection_index(tmp_path: Path) -> None:
    public = tmp_path / "public"
    write_json(public / "collections.json", {"收集表列表": [{"数据文件": "data/demo/index.json"}]})
    write_json(public / "data" / "demo" / "index.json", {"提交序号列表": {}})

    with pytest.raises(ValueError, match="提交序号列表"):
        stamp_deploy_time(public, public / "collections.json", "2026-06-11 23:59:00")
