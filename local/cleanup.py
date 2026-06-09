from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from contract import dump_json, normalize_filename_key, now_text
from attachments import build_uploaded_refs


def execute_source_attachment_cleanup(
    *,
    df: pd.DataFrame,
    selected_labels: list[str],
    attachments_dir: Path,
    attachment_lookup: dict[str, str],
    duplicate_lookup: dict[str, list[str]],
    course_out_dir: Path,
    mode: str,
) -> Path:
    if mode not in {"dry-run", "apply"}:
        raise ValueError(f"未知清理模式: {mode}")
    selected = set(selected_labels)
    uploaded_refs = build_uploaded_refs(df)
    df_selected = df[df["_submission_label"].isin(selected)]
    unique_keys = sorted({normalize_filename_key(name) for name in df_selected["_uploaded_filename"].tolist() if name})
    attachments_root = attachments_dir.resolve()
    planned: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    deleted: list[str] = []
    failures: list[dict[str, Any]] = []

    for key in unique_keys:
        outside_refs = sorted(
            ref
            for ref in uploaded_refs.get(key, set())
            if ref.split("|", 1)[0] not in selected
        )
        if outside_refs:
            protected.append({"附件键": key, "保护原因": "其他提交序号/提交内容仍引用", "引用": outside_refs})
            continue
        if key in duplicate_lookup:
            ambiguous.append({"附件键": key, "本地候选附件名": duplicate_lookup[key]})
            continue
        filename = attachment_lookup.get(key)
        if not filename:
            missing.append({"附件键": key, "原因": "本地同步目录未找到"})
            continue
        path = (attachments_dir / filename).resolve()
        try:
            path.relative_to(attachments_root)
        except ValueError:
            protected.append({"附件键": key, "本地附件名": filename, "保护原因": "目标不在附件目录内"})
            continue
        item = {"附件键": key, "本地附件名": filename, "本地绝对路径": str(path)}
        planned.append(item)
        if mode == "apply":
            try:
                if path.exists():
                    path.unlink()
                    deleted.append(filename)
                else:
                    failures.append({"本地附件名": filename, "原因": "执行删除时已不存在"})
            except OSError as err:
                failures.append({"本地附件名": filename, "原因": str(err)})

    report = {
        "模式": mode,
        "统计生成时间": now_text(),
        "附件目录": str(attachments_root),
        "选择提交序号": selected_labels,
        "汇总": {
            "计划删除附件数": len(planned),
            "实际删除附件数": len(deleted),
            "跨提交保护附件数": len(protected),
            "本地歧义附件数": len(ambiguous),
            "本地缺失附件数": len(missing),
            "删除失败附件数": len(failures),
        },
        "计划删除附件": planned,
        "实际删除附件": deleted,
        "跨提交保护附件": protected,
        "本地歧义附件": ambiguous,
        "本地缺失附件": missing,
        "删除失败附件": failures,
    }
    report_path = course_out_dir / "stats" / "source_attachment_cleanup.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(dump_json(report), encoding="utf-8")
    return report_path
