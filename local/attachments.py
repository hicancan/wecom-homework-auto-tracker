from __future__ import annotations

from pathlib import Path

from contract import normalize_filename_key


def find_attachments_dir(collection_title: str, attachments_root: Path, attachments_override: str) -> Path:
    if attachments_override.strip():
        path = Path(attachments_override).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"指定附件目录不存在: {path}")
        return path
    if not attachments_root.exists():
        raise FileNotFoundError(f"附件根目录不存在: {attachments_root}")
    candidates = [
        path
        for path in attachments_root.iterdir()
        if path.is_dir() and (collection_title in path.name or path.name.startswith(collection_title))
    ]
    preferred = [path for path in candidates if "收集的文件" in path.name]
    if len(preferred) == 1:
        return preferred[0].resolve()
    if len(preferred) > 1:
        raise ValueError("匹配到多个收集表附件目录:\n" + "\n".join(str(path) for path in preferred))
    if len(candidates) == 1:
        return candidates[0].resolve()
    if len(candidates) > 1:
        raise ValueError("匹配到多个收集表目录:\n" + "\n".join(str(path) for path in candidates))
    raise FileNotFoundError(f"未找到收集表附件目录: {collection_title}")


def build_attachment_lookup(attachments_dir: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    grouped: dict[str, list[str]] = {}
    for path in attachments_dir.iterdir():
        if not path.is_file():
            continue
        grouped.setdefault(normalize_filename_key(path.name), []).append(path.name)
    unique: dict[str, str] = {}
    duplicates: dict[str, list[str]] = {}
    for key, names in grouped.items():
        if len(names) == 1:
            unique[key] = names[0]
        else:
            duplicates[key] = sorted(names)
    return unique, duplicates


def build_uploaded_refs(df: pd.DataFrame) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        filename = str(row["_uploaded_filename"]).strip()
        if not filename:
            continue
        key = normalize_filename_key(filename)
        refs.setdefault(key, set()).add(f"{row['_submission_label']}|{row['_content_label']}")
    return refs
