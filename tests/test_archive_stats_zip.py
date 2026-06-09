from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from archive import active_archive_path, archive_entry_id, set_non_active_status, upsert_active_file
from stats import make_submission_stat
from zip_writer import create_submission_zip


def build_manifest_with_late_and_invalid(tmp_path: Path) -> tuple[Path, dict, dict, str, dict, dict]:
    collection_dir = tmp_path / "collections" / "demo"
    collection_dir.mkdir(parents=True)
    valid_source = tmp_path / "late.docx"
    valid_source.write_text("valid", encoding="utf-8")

    meta = {
        "收集表ID": "demo",
        "标题": "示例主题[B240401][大二下]",
        "主题": "示例主题",
        "对象": "B240401",
        "周期": "大二下",
        "状态": "active",
    }
    manifest = {
        "schema_version": 2,
        "收集表ID": "demo",
        "标题": meta["标题"],
        "主题": meta["主题"],
        "对象": meta["对象"],
        "周期": meta["周期"],
        "状态": "active",
        "entries": {},
    }
    content = "作业(.doc/.docx)"

    late_student = {"班级": "B240401", "学号": "B24040101", "姓名": "张三", "姓名标准化": "张三"}
    invalid_student = {"班级": "B240401", "学号": "B24040102", "姓名": "李四", "姓名标准化": "李四"}
    late_entry = {
        **late_student,
        "提交序号": "第1次",
        "提交内容": content,
        "提交内容名": "作业",
        "允许后缀": [".doc", ".docx"],
        "提交时间": "2026-06-09 10:00:00",
        "源附件名": "late.docx",
        "用户类型": "学生",
    }
    late_id = archive_entry_id(late_student["学号"], "第1次", content)
    upsert_active_file(
        manifest,
        collection_dir,
        late_id,
        valid_source,
        active_archive_path(collection_dir, "第1次", "作业", "B240401", "B24040101张三.docx"),
        late_entry,
    )

    invalid_entry = {
        **invalid_student,
        "提交序号": "第1次",
        "提交内容": content,
        "提交内容名": "作业",
        "允许后缀": [".doc", ".docx"],
        "提交时间": "2026-06-09 10:05:00",
        "源附件名": "bad.txt",
        "用户类型": "学生",
    }
    invalid_id = archive_entry_id(invalid_student["学号"], "第1次", content)
    set_non_active_status(manifest, collection_dir, invalid_id, invalid_entry, "invalid", "后缀 .txt 不符合 作业(.doc/.docx)")
    return collection_dir, meta, manifest, content, late_student, invalid_student


def test_cutoff_mode_excludes_late_submission_and_invalid_suffix_is_not_zipped(tmp_path: Path) -> None:
    collection_dir, meta, manifest, content, late_student, invalid_student = build_manifest_with_late_and_invalid(tmp_path)

    df = pd.DataFrame(
        {
            "_submission_label": ["第1次", "第1次"],
            "_record_time": pd.to_datetime(["2026-06-09 10:00:00", "2026-06-09 10:05:00"]),
        }
    )
    stat = make_submission_stat(
        df=df,
        columns={},
        meta=meta,
        manifest=manifest,
        submission_label="第1次",
        content_labels=[content],
        students_by_class={"B240401": [late_student, invalid_student]},
        other_students_by_name={},
        cutoff=pd.Timestamp("2026-06-09 09:00:00"),
    )

    assert stat["汇总"]["应交总人数"] == 2
    assert stat["发布模式"] == "截止模式"
    assert stat["允许补交"] is False
    assert stat["汇总"]["已交总人数"] == 0
    assert stat["汇总"]["已补交总人数"] == 0
    assert stat["汇总"]["后缀格式无效总人数"] == 0
    assert stat["班级统计"]["B240401"]["已补交名单"] == []
    assert stat["班级统计"]["B240401"]["后缀格式无效名单"] == []

    zip_path = create_submission_zip(collection_dir, "第1次", manifest, pd.Timestamp("2026-06-09 09:00:00"))
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()

    assert names == []


def test_makeup_window_counts_late_submission_and_zip_is_class_first(tmp_path: Path) -> None:
    collection_dir, meta, manifest, content, late_student, invalid_student = build_manifest_with_late_and_invalid(tmp_path)

    df = pd.DataFrame(
        {
            "_submission_label": ["第1次", "第1次"],
            "_record_time": pd.to_datetime(["2026-06-09 10:00:00", "2026-06-09 10:05:00"]),
        }
    )
    stat = make_submission_stat(
        df=df,
        columns={},
        meta=meta,
        manifest=manifest,
        submission_label="第1次",
        content_labels=[content],
        students_by_class={"B240401": [late_student, invalid_student]},
        other_students_by_name={},
        cutoff=pd.Timestamp("2026-06-09 09:00:00"),
        publish_mode="makeup-window",
        makeup_window_end=pd.Timestamp("2026-06-09 22:40:00"),
    )

    assert stat["发布模式"] == "补交窗口模式"
    assert stat["允许补交"] is True
    assert stat["补交窗口开始时间"] == "2026-06-09 09:00:00"
    assert stat["补交窗口结束时间"] == "2026-06-09 22:40:00"
    assert stat["汇总"]["已交总人数"] == 1
    assert stat["汇总"]["已补交总人数"] == 1
    assert stat["汇总"]["后缀格式无效总人数"] == 1
    assert stat["班级统计"]["B240401"]["已补交名单"] == ["B24040101"]
    assert stat["班级统计"]["B240401"]["后缀格式无效名单"] == ["B24040102"]

    zip_path = create_submission_zip(
        collection_dir,
        "第1次",
        manifest,
        pd.Timestamp("2026-06-09 09:00:00"),
        pd.Timestamp("2026-06-09 09:00:00"),
        pd.Timestamp("2026-06-09 22:40:00"),
    )
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()

    assert any(name == "B240401/作业/B24040101张三.docx" for name in names)
    assert not any("B24040102" in name for name in names)
