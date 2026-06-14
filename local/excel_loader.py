from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from contract import normalize_name, normalize_text, normalize_uploaded_filename, parse_collection_title, parse_submission_content


def discover_collection_excels(config_dir: Path) -> dict[str, Path]:
    collections: dict[str, Path] = {}
    for path in sorted(config_dir.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        parse_collection_title(path.stem)
        collections[path.stem] = path
    return collections


def require_column(df: pd.DataFrame, column: str, excel_path: Path) -> str:
    if column not in df.columns:
        raise ValueError(f"Excel 缺少列 `{column}`: {excel_path}")
    return column


def load_collection_excel(
    excel_path: Path,
    default_content: str = "",
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    """Load and validate a collection Excel.

    **TEMPORARY**: `default_content` fills empty 提交内容 cells for legacy
    collection tables created before WeCom added the 提交内容 field.
    New tables should never need this.
    """
    meta = parse_collection_title(excel_path.stem)
    df = pd.read_excel(excel_path)
    columns = {
        "name": require_column(df, "填写人", excel_path),
        "department": require_column(df, "所在部门", excel_path),
        "time": require_column(df, "填写时间", excel_path),
        "submission": require_column(df, "提交序号", excel_path),
        "content": require_column(df, "提交内容", excel_path),
        "file": require_column(df, "请上传对应文件", excel_path),
        "user_type": require_column(df, "用户类型", excel_path),
    }
    df = df.copy()

    # TEMPORARY: auto-fill empty content cells for legacy collection tables.
    if default_content:
        mask = (
            df[columns["content"]].isna()
            | (df[columns["content"]].astype(str).str.strip().isin(["", "nan"]))
        )
        if mask.any():
            df.loc[mask, columns["content"]] = default_content

    df["_name_norm"] = df[columns["name"]].map(normalize_name)
    df["_submission_label"] = df[columns["submission"]].map(normalize_text)
    df["_content_label"] = df[columns["content"]].map(normalize_text)
    df["_uploaded_filename"] = df[columns["file"]].map(normalize_uploaded_filename)
    df["_record_time"] = pd.to_datetime(df[columns["time"]], errors="raise")

    blank_submission = df.index[df["_submission_label"] == ""].tolist()
    blank_content = df.index[df["_content_label"] == ""].tolist()
    if blank_submission:
        raise ValueError(f"提交序号不能为空: {excel_path}, 行号={blank_submission[:10]}")
    if blank_content:
        raise ValueError(f"提交内容不能为空: {excel_path}, 行号={blank_content[:10]}")

    for content in sorted(df["_content_label"].unique()):
        parse_submission_content(content)
    return df, meta, columns
