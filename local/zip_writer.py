from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from archive import merged_entry_version, version_sort_key
from contract import dump_json, entry_time_in_publication_window, sanitize_filename_component


def active_entries_for_submission(
    manifest: dict[str, Any],
    submission_label: str,
    cutoff: pd.Timestamp | None = None,
    makeup_window_start: pd.Timestamp | None = None,
    makeup_window_end: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    entries = []
    for entry in manifest.get("entries", {}).values():
        if not isinstance(entry, dict) or entry.get("提交序号") != submission_label:
            continue
        versions = [
            version
            for version in entry.get("versions", [])
            if isinstance(version, dict)
            and entry_time_in_publication_window(version, cutoff, makeup_window_start, makeup_window_end)
        ]
        if not versions:
            continue
        latest = sorted(versions, key=version_sort_key)[-1]
        if latest.get("状态") == "active":
            entries.append(merged_entry_version(entry, latest))
    return sorted(entries, key=lambda item: (str(item.get("班级", "")), str(item.get("提交内容名", "")), str(item.get("学号", ""))))


def create_submission_zip(
    course_out_dir: Path,
    submission_label: str,
    manifest: dict[str, Any],
    cutoff: pd.Timestamp | None = None,
    makeup_window_start: pd.Timestamp | None = None,
    makeup_window_end: pd.Timestamp | None = None,
) -> Path:
    zip_dir = course_out_dir / "zip"
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / f"{sanitize_filename_component(submission_label)}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry in active_entries_for_submission(manifest, submission_label, cutoff, makeup_window_start, makeup_window_end):
            rel = str(entry.get("文件相对路径", "")).strip()
            if not rel:
                continue
            source = course_out_dir / rel
            if not source.exists():
                continue
            arcname = "/".join(
                [
                    sanitize_filename_component(str(entry.get("班级", ""))),
                    sanitize_filename_component(str(entry.get("提交内容名", ""))),
                    source.name,
                ]
            )
            zf.write(source, arcname)
    return zip_path


def write_submission_reports(
    course_out_dir: Path,
    submission_label: str,
    stat: dict[str, Any],
) -> None:
    stats_dir = course_out_dir / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)
    token = sanitize_filename_component(submission_label)
    (stats_dir / f"{token}.json").write_text(dump_json(stat), encoding="utf-8")
    invalid = stat.get("后缀格式无效", {})
    if int(invalid.get("总人数", 0) or 0) > 0:
        (stats_dir / f"{token}.invalid_suffix.json").write_text(dump_json(invalid), encoding="utf-8")
