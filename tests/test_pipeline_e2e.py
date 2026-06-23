from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from pipeline import process_collection


TITLE = "数学建模期末大作业[B240402][大二下]"
CONTENT = "期末大作业(.doc/.docx/.pdf)"
COLLECTION_ID = "math-modeling-final-b240402-sophomore-spring"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_fixture(tmp_path: Path) -> tuple[Path, dict, dict]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    excel_path = config_dir / f"{TITLE}.xlsx"
    pd.DataFrame(
        {
            "填写人": ["张三", "李四", "王五"],
            "所在部门": ["B240402", "B240402", "B240402"],
            "填写时间": ["2026-06-10 09:00:00", "2026-06-10 11:00:00", "2026-06-10 09:30:00"],
            "提交序号": ["第1次", "第1次", "第1次"],
            "提交内容": [CONTENT, CONTENT, CONTENT],
            "请上传对应文件": ["zhang.pdf", "li.docx", "wang.txt"],
            "用户类型": ["企业微信用户", "企业微信用户", "企业微信用户"],
        }
    ).to_excel(excel_path, index=False)

    attachments_dir = tmp_path / "attachments" / f"{TITLE}收集的文件"
    attachments_dir.mkdir(parents=True)
    (attachments_dir / "zhang.pdf").write_text("valid pdf", encoding="utf-8")
    (attachments_dir / "li.docx").write_text("valid docx", encoding="utf-8")
    (attachments_dir / "wang.txt").write_text("invalid txt", encoding="utf-8")

    students_path = config_dir / "students.json"
    write_json(
        students_path,
        [
            {"班级": "B240402", "学号": "B24040201", "姓名": "张三"},
            {"班级": "B240402", "学号": "B24040202", "姓名": "李四"},
            {"班级": "B240402", "学号": "B24040203", "姓名": "王五"},
        ],
    )

    cfg = {
        "students": str(students_path),
        "attachments_root": str(tmp_path / "attachments"),
        "out_root": str(tmp_path / "out"),
        "web_data_root": str(tmp_path / "webapp" / "public" / "data"),
        "collection_index": str(tmp_path / "webapp" / "public" / "collections.json"),
    }
    meta = {
        "收集表ID": COLLECTION_ID,
        "标题": TITLE,
        "主题": "数学建模期末大作业",
        "对象": "B240402",
        "周期": "大二下",
        "状态": "active",
        "classes": ["B240402"],
    }
    return excel_path, cfg, meta


def read_stat(tmp_path: Path) -> dict:
    path = tmp_path / "webapp" / "public" / "data" / COLLECTION_ID / "seq-001.json"
    return json.loads(path.read_text(encoding="utf-8"))


def zip_names(tmp_path: Path) -> list[str]:
    zip_path = tmp_path / "out" / "collections" / COLLECTION_ID / "zip" / "第1次.zip"
    with zipfile.ZipFile(zip_path) as archive:
        return sorted(archive.namelist())


def assert_public_json_has_no_legacy_fields(tmp_path: Path) -> None:
    for path in (tmp_path / "webapp" / "public").rglob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "课程列表" not in data
        assert "课程" not in data
        assert "作业" not in data


def test_pipeline_cutoff_mode_counts_only_deadline_valid_files_and_zip_excludes_invalid(tmp_path: Path) -> None:
    excel_path, cfg, meta = build_fixture(tmp_path)

    process_collection(
        collection_id=COLLECTION_ID,
        excel_path=excel_path,
        cfg=cfg,
        repo_root=tmp_path,
        requested_labels=["第1次"],
        attachments_override="",
        cutoff_policy="manual",
        manual_cutoffs={"第1次": pd.Timestamp("2026-06-10 10:00:00")},
        cleanup_mode="off",
        cleanup_only=False,
        skip_unknown=False,
        zip_to_desktop=False,
        publish_mode="cutoff",
        makeup_window_start=None,
        makeup_window_end=None,
        configured_meta=meta,
    )

    stat = read_stat(tmp_path)
    assert stat["统计截止时间"] == "2026-06-10 10:00:00"
    assert stat["发布模式"] == "截止模式"
    assert stat["允许补交"] is False
    assert stat["汇总"]["应交总人数"] == 3
    assert stat["汇总"]["已提交总人数"] == 1
    assert stat["汇总"]["后缀无效总人数"] == 1
    assert zip_names(tmp_path) == ["B240402/期末大作业/B24040201张三.pdf"]
    assert_public_json_has_no_legacy_fields(tmp_path)


def test_pipeline_makeup_window_counts_only_window_late_files_and_keeps_invalid_out_of_zip(tmp_path: Path) -> None:
    excel_path, cfg, meta = build_fixture(tmp_path)

    process_collection(
        collection_id=COLLECTION_ID,
        excel_path=excel_path,
        cfg=cfg,
        repo_root=tmp_path,
        requested_labels=["第1次"],
        attachments_override="",
        cutoff_policy="manual",
        manual_cutoffs={"第1次": pd.Timestamp("2026-06-10 10:00:00")},
        cleanup_mode="off",
        cleanup_only=False,
        skip_unknown=False,
        zip_to_desktop=False,
        publish_mode="makeup-window",
        makeup_window_start=pd.Timestamp("2026-06-10 10:00:00"),
        makeup_window_end=pd.Timestamp("2026-06-10 12:00:00"),
        configured_meta=meta,
    )

    stat = read_stat(tmp_path)
    assert stat["发布模式"] == "补交窗口模式"
    assert stat["允许补交"] is True
    assert stat["汇总"]["已提交总人数"] == 2
    assert stat["汇总"]["已补交总人数"] == 1
    assert stat["汇总"]["后缀无效总人数"] == 1
    assert stat["班级统计"]["B240402"]["已补交名单"] == ["B24040202"]
    assert zip_names(tmp_path) == [
        "B240402/期末大作业/B24040201张三.pdf",
        "B240402/期末大作业/B24040202李四.docx",
    ]
    assert_public_json_has_no_legacy_fields(tmp_path)
