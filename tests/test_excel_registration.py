from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from excel_loader import load_collection_excel
from scripts.run_extract_interactive import discover_unregistered_excels


def write_collection_excel(path: Path, content: object) -> None:
    pd.DataFrame(
        {
            "填写人": ["郭嘉伟"],
            "所在部门": ["B240402"],
            "填写时间": ["2026-06-11 22:37"],
            "提交序号": ["第1次"],
            "提交内容": [content],
            "请上传对应文件": ["B24040226郭嘉伟.pdf"],
            "用户类型": ["企业微信用户"],
        }
    ).to_excel(path, index=False)


def test_unregistered_excel_can_be_discovered_with_suggested_collection_id(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    excel = config_dir / "数学建模期末大作业[B240402][大二下].xlsx"
    write_collection_excel(excel, "期末大作业(.doc/.docx/.pdf)")

    candidates = discover_unregistered_excels(
        tmp_path,
        {
            "collections_dir": "config",
            "collections": {},
        },
    )

    assert len(candidates) == 1
    assert candidates[0].suggested_collection_id == "math-modeling-final-b240402-sophomore-spring"
    assert candidates[0].classes == ["B240402"]
    assert candidates[0].labels == {"第1次": ["期末大作业(.doc/.docx/.pdf)"]}


def test_empty_submission_content_fails_fast(tmp_path: Path) -> None:
    excel = tmp_path / "数学建模期末大作业[B240402][大二下].xlsx"
    write_collection_excel(excel, "")

    with pytest.raises(ValueError, match="提交内容不能为空"):
        load_collection_excel(excel)
