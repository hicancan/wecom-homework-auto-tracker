from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


TITLE_RE = r"^[^\[\]]+\[[^\[\]]+\](?:\[[^\[\]]+\])?$"


@dataclass(frozen=True)
class CollectionConfig:
    collection_id: str
    title: str
    excel: Path
    status: str


@dataclass(frozen=True)
class PlanItem:
    collection_id: str
    title: str
    labels: list[str]
    cutoff_policy: str
    manual_cutoffs: dict[str, str]
    publish_mode: str
    makeup_window_start: str
    makeup_window_end: str


def normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def format_time(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def parse_selection(raw: str, count: int) -> list[int]:
    text = raw.strip().lower().replace("，", ",").replace("、", ",")
    if text == "all":
        return list(range(1, count + 1))
    picked: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = [x.strip() for x in part.split("-", 1)]
            start = int(left)
            end = int(right)
            if start > end:
                raise ValueError(f"范围无效: {part}")
            picked.update(range(start, end + 1))
        else:
            picked.add(int(part))
    invalid = [idx for idx in picked if idx < 1 or idx > count]
    if invalid:
        raise ValueError(f"编号超出范围: {invalid}")
    return sorted(picked)


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"配置不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"配置必须是 JSON 对象: {path}")
    return data


def discover_collections(repo_root: Path, cfg: dict) -> list[CollectionConfig]:
    raw = cfg.get("collections")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("配置缺少 collections。")
    items: list[CollectionConfig] = []
    for collection_id, item in raw.items():
        if not isinstance(item, dict):
            raise ValueError(f"collections.{collection_id} 必须是对象。")
        title = normalize_text(item.get("title"))
        if not title or re.fullmatch(TITLE_RE, title) is None:
            raise ValueError(f"收集表标题不符合新模型: {collection_id} -> {title}")
        excel_text = normalize_text(item.get("excel"))
        if not excel_text:
            continue
        excel = Path(excel_text)
        if not excel.is_absolute():
            excel = (repo_root / excel).resolve()
        if not excel.exists():
            raise FileNotFoundError(f"Excel 不存在: {collection_id} -> {excel}")
        if excel.stem != title:
            raise ValueError(f"Excel 文件名必须等于收集表标题: {collection_id} -> {excel.name}")
        items.append(
            CollectionConfig(
                collection_id=str(collection_id),
                title=title,
                excel=excel,
                status=normalize_text(item.get("status")) or "active",
            )
        )
    return sorted(items, key=lambda item: item.collection_id)


def discover_labels(excel_path: Path) -> tuple[dict[str, list[str]], pd.DataFrame]:
    df = pd.read_excel(excel_path)
    for required in ["提交序号", "提交内容", "请上传对应文件", "填写时间"]:
        if required not in df.columns:
            raise ValueError(f"Excel 缺少 `{required}`: {excel_path}")
    df = df.copy()
    df["_record_time"] = pd.to_datetime(df["填写时间"], errors="raise")
    labels: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        label = normalize_text(row["提交序号"])
        content = normalize_text(row["提交内容"])
        if not label or not content:
            raise ValueError(f"提交序号/提交内容不能为空: {excel_path}")
        labels.setdefault(label, [])
        if content not in labels[label]:
            labels[label].append(content)
    return labels, df


def load_published_cutoffs(repo_root: Path, collection_id: str) -> dict[str, pd.Timestamp]:
    index_path = repo_root / "webapp" / "public" / "data" / collection_id / "index.json"
    if not index_path.exists():
        return {}
    data = json.loads(index_path.read_text(encoding="utf-8"))
    refs = data.get("提交序号列表", [])
    if not isinstance(refs, list):
        raise ValueError(f"公开索引缺少提交序号列表: {index_path}")
    cutoffs: dict[str, pd.Timestamp] = {}
    for item in refs:
        if not isinstance(item, dict):
            continue
        label = normalize_text(item.get("提交序号", ""))
        rel = str(item.get("数据文件", "")).removeprefix("data/")
        if not label or not rel:
            continue
        stat_path = repo_root / "webapp" / "public" / "data" / rel
        if not stat_path.exists():
            continue
        stat = json.loads(stat_path.read_text(encoding="utf-8"))
        cutoff_text = stat.get("统计截止时间") or stat.get("最后提交时间")
        if cutoff_text:
            cutoffs[label] = pd.to_datetime(cutoff_text, errors="raise")
    return cutoffs


def latest_time_for_label(df: pd.DataFrame, label: str) -> pd.Timestamp:
    selected = df[df["提交序号"].map(normalize_text) == label]
    if selected.empty:
        raise ValueError(f"提交序号没有记录: {label}")
    return selected["_record_time"].max()


def choose_cutoff_policy(
    *,
    item: CollectionConfig,
    labels: list[str],
    labels_df: pd.DataFrame,
    published_cutoffs: dict[str, pd.Timestamp],
) -> tuple[str, dict[str, str]]:
    print("\n统计截止时间:")
    for label in labels:
        latest = latest_time_for_label(labels_df, label)
        cutoff = published_cutoffs.get(label)
        rows_for_label = labels_df[labels_df["提交序号"].map(normalize_text) == label]
        late_rows = int((rows_for_label["_record_time"] > cutoff).sum()) if cutoff is not None else 0
        print(
            f"  {item.collection_id} | {label}: "
            f"已发布截止={format_time(cutoff) or '无'} | Excel最新={format_time(latest)} | 截止后记录={late_rows}"
        )
    default_policy = "keep"
    print("截止策略: keep=已发布保留/新序号首次发布, advance=全部推进到 Excel 最新, manual=手动指定")
    raw = input(f"请选择截止策略 [keep/advance/manual]（默认 {default_policy}）: ").strip().lower()
    policy = raw or default_policy
    if policy not in {"keep", "advance", "manual"}:
        raise ValueError(f"未知截止策略: {policy}")
    manual: dict[str, str] = {}
    if policy == "manual":
        for label in labels:
            default_time = published_cutoffs.get(label) or latest_time_for_label(labels_df, label)
            raw_time = input(f"{label} 截止时间（默认 {format_time(default_time)}）: ").strip()
            manual[label] = raw_time or format_time(default_time)
    return policy, manual


def default_makeup_window_end() -> str:
    return datetime.now().strftime("%Y-%m-%d") + " 22:40:00"


def choose_publish_mode() -> tuple[str, str, str]:
    print("\n发布模式:")
    print("  cutoff=截止模式，只发布截止时间内有效提交，ZIP 不含补交")
    print("  makeup-window=补交窗口模式，发布截止内 + 补交窗口内有效提交，ZIP 含补交")
    raw = input("是否开启补交窗口？[y/N]: ").strip().lower()
    if raw not in {"y", "yes"}:
        return "cutoff", "", ""

    start = input("补交窗口开始时间（默认：各提交序号统计截止时间之后）: ").strip()
    default_end = default_makeup_window_end()
    end = input(f"补交窗口结束时间（默认 {default_end}）: ").strip() or default_end
    pd.to_datetime(end, errors="raise")
    if start:
        pd.to_datetime(start, errors="raise")
    return "makeup-window", start, end


def choose_items(repo_root: Path, collections: list[CollectionConfig]) -> list[PlanItem]:
    print("\n可选收集表:")
    for idx, item in enumerate(collections, 1):
        print(f"  {idx}. {item.collection_id} | {item.title} | {item.status}")
    while True:
        raw = input("请选择收集表编号（如 1,3 或 all）: ")
        try:
            collection_indices = parse_selection(raw, len(collections))
            if collection_indices:
                break
        except Exception as err:
            print(f"输入无效: {err}")

    plan: list[PlanItem] = []
    for collection_idx in collection_indices:
        item = collections[collection_idx - 1]
        labels_map, labels_df = discover_labels(item.excel)
        labels = list(labels_map.keys())
        print(f"\n选择提交序号: {item.collection_id} | {item.title}")
        for idx, label in enumerate(labels, 1):
            print(f"  {idx}. {label} | {', '.join(labels_map[label])}")
        while True:
            raw = input("请选择提交序号编号（如 1,3 或 all）: ")
            try:
                label_indices = parse_selection(raw, len(labels))
                if label_indices:
                    break
            except Exception as err:
                print(f"输入无效: {err}")
        selected_labels = [labels[i - 1] for i in label_indices]
        cutoff_policy, manual_cutoffs = choose_cutoff_policy(
            item=item,
            labels=selected_labels,
            labels_df=labels_df,
            published_cutoffs=load_published_cutoffs(repo_root, item.collection_id),
        )
        publish_mode, makeup_window_start, makeup_window_end = choose_publish_mode()
        plan.append(
            PlanItem(
                collection_id=item.collection_id,
                title=item.title,
                labels=selected_labels,
                cutoff_policy=cutoff_policy,
                manual_cutoffs=manual_cutoffs,
                publish_mode=publish_mode,
                makeup_window_start=makeup_window_start,
                makeup_window_end=makeup_window_end,
            )
        )
    return plan


def build_extract_cmd(
    python_exe: Path,
    repo_root: Path,
    config_path: Path,
    item: PlanItem,
    *,
    cleanup_mode: str = "off",
    cleanup_only: bool = False,
) -> list[str]:
    cmd = [
        str(python_exe),
        str(repo_root / "local" / "extract_homework.py"),
        "--config",
        str(config_path),
        "--collection-id",
        item.collection_id,
    ]
    for label in item.labels:
        cmd.extend(["--label", label])
    cmd.extend(["--cutoff-policy", item.cutoff_policy])
    for label, cutoff in item.manual_cutoffs.items():
        cmd.extend(["--cutoff", f"{label}={cutoff}"])
    cmd.extend(["--publish-mode", item.publish_mode])
    if item.makeup_window_start:
        cmd.extend(["--makeup-window-start", item.makeup_window_start])
    if item.makeup_window_end:
        cmd.extend(["--makeup-window-end", item.makeup_window_end])
    if cleanup_mode != "off":
        cmd.extend(["--cleanup-source-attachments", cleanup_mode])
    if cleanup_only:
        cmd.append("--cleanup-only")
    return cmd


def run_extracts(
    python_exe: Path,
    repo_root: Path,
    config_path: Path,
    plan: list[PlanItem],
    *,
    cleanup_mode: str = "off",
    cleanup_only: bool = False,
) -> int:
    for item in plan:
        print(f"\n开始处理: {item.collection_id} labels={', '.join(item.labels)}")
        proc = subprocess.run(
            build_extract_cmd(
                python_exe,
                repo_root,
                config_path,
                item,
                cleanup_mode=cleanup_mode,
                cleanup_only=cleanup_only,
            ),
            cwd=repo_root,
        )
        if proc.returncode != 0:
            print(f"处理失败: {item.collection_id}")
            return proc.returncode
    return 0


def prompt_source_cleanup(python_exe: Path, repo_root: Path, config_path: Path, plan: list[PlanItem]) -> int:
    print("\n源文件清理默认跳过。可选模式: skip / dry-run / apply")
    raw = input("是否清理企业微信本地同步源文件？[skip/dry-run/apply]: ").strip().lower()
    if raw in {"", "skip", "s", "n", "no"}:
        print("已跳过源文件清理。")
        return 0
    if raw in {"dry-run", "dry", "d"}:
        return run_extracts(python_exe, repo_root, config_path, plan, cleanup_mode="dry-run", cleanup_only=True)
    if raw in {"apply", "a"}:
        confirm = input("确认删除源文件请输入 APPLY: ").strip()
        if confirm != "APPLY":
            print("未输入 APPLY，已取消源文件清理。")
            return 0
        return run_extracts(python_exe, repo_root, config_path, plan, cleanup_mode="apply", cleanup_only=True)
    print(f"未知清理模式: {raw}")
    return 1


def git_commit_public(repo_root: Path, auto_push: bool) -> None:
    status = subprocess.run(
        ["git", "status", "--short", "--", "webapp/public"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if not status:
        print("\nwebapp/public 无变更，跳过 git 提交。")
        return
    subprocess.run(["git", "add", "webapp/public"], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "chore(data): update collection stats"], cwd=repo_root, check=True)
    if auto_push:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        subprocess.run(["git", "push", "origin", branch], cwd=repo_root, check=True)


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="新模型增量收集交互入口")
    parser.add_argument("--config", default=str(repo_root / "config" / "config.json"))
    parser.add_argument("--no-auto-push", dest="auto_push", action="store_false")
    parser.add_argument("--no-git", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        fallback = repo_root / "config" / "local.config.json"
        config_path = fallback if fallback.exists() else config_path
    cfg = load_config(config_path)
    collections = discover_collections(repo_root, cfg)
    if not collections:
        print("未发现可提取的收集表 Excel。")
        return 1
    plan = choose_items(repo_root, collections)
    print("\n执行计划:")
    for item in plan:
        window = ""
        if item.publish_mode == "makeup-window":
            window = f" | window={item.makeup_window_start or 'cutoff'} -> {item.makeup_window_end}"
        print(f"- {item.collection_id}: {', '.join(item.labels)} | cutoff={item.cutoff_policy} | mode={item.publish_mode}{window}")
    if input("确认执行？[y/N]: ").strip().lower() != "y":
        print("已取消。")
        return 1
    code = run_extracts(Path(sys.executable), repo_root, config_path, plan)
    if code != 0:
        return code
    cleanup_code = prompt_source_cleanup(Path(sys.executable), repo_root, config_path, plan)
    if cleanup_code != 0:
        return cleanup_code
    if args.no_git:
        print("已按参数跳过 git。")
        return 0
    git_commit_public(repo_root, args.auto_push)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
