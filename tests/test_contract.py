from __future__ import annotations

import pytest

from contract import parse_collection_title, parse_submission_content, require_collection_id


def test_parse_collection_title_requires_new_shape() -> None:
    meta = parse_collection_title("算法分析与设计作业[B240401-03][大二下]")

    assert meta == {
        "标题": "算法分析与设计作业[B240401-03][大二下]",
        "主题": "算法分析与设计作业",
        "对象": "B240401-03",
        "周期": "大二下",
    }


def test_parse_submission_content_binds_suffix_contract() -> None:
    content = parse_submission_content("实验报告(.doc/.docx)")

    assert content["提交内容名"] == "实验报告"
    assert content["允许后缀"] == (".doc", ".docx")


@pytest.mark.parametrize("value", ["旧标题", "主题[]", "主题[对象][周期][多余]"])
def test_invalid_collection_title_fails_fast(value: str) -> None:
    with pytest.raises(ValueError):
        parse_collection_title(value)


@pytest.mark.parametrize("value", ["作业", "作业（.doc）", "作业(.doc/.docx"])
def test_invalid_submission_content_fails_fast(value: str) -> None:
    with pytest.raises(ValueError):
        parse_submission_content(value)


@pytest.mark.parametrize("value", ["ai-python-exp-b240402-sophomore-spring", "seq-001"])
def test_collection_id_accepts_ascii_kebab_case(value: str) -> None:
    assert require_collection_id(value) == value


@pytest.mark.parametrize("value", ["算法", "AI Python", "bad_id", ""])
def test_collection_id_rejects_unstable_values(value: str) -> None:
    with pytest.raises(ValueError):
        require_collection_id(value)
