from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


TITLE_RE = r"^.+\[[^\[\]]+\](?:\[[^\[\]]+\])?$"


@dataclass(frozen=True)
class PlanItem:
    course: str
    excel: Path
    labels: list[str]
    cutoff_policy: str
    manual_cutoffs: dict[str, str]


def normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def sanitize_filename_component(text: object) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", str(text or "")).strip()


def format_time(value: object) -> str:
    if pd.isna(value):
        return ""
    return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def is_new_model_title(title: str) -> bool:
    import re

    return re.fullmatch(TITLE_RE, title.strip()) is not None


def discover_courses(courses_dir: Path) -> dict[str, Path]:
    courses: dict[str, Path] = {}
    for path in sorted(courses_dir.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        if not is_new_model_title(path.stem):
            raise ValueError(f"发现非新模型 Excel，已拒绝参与提取: {path.name}")
        courses[path.stem] = path
    return courses


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


def load_published_cutoffs(repo_root: Path, course: str) -> dict[str, pd.Timestamp]:
    index_path = repo_root / "webapp" / "public" / "data" / f"{sanitize_filename_component(course)}.index.json"
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
    course: str,
    labels: list[str],
    labels_df: pd.DataFrame,
    published_cutoffs: dict[str, pd.Timestamp],
) -> tuple[str, dict[str, str]]:
    print("\n统计截止时间:")
    for label in labels:
        latest = latest_time_for_label(labels_df, label)
        cutoff = published_cutoffs.get(label)
        late_rows = int((labels_df[(labels_df["提交序号"].map(normalize_text) == label)]["_record_time"] > cutoff).sum()) if cutoff is not None else 0
        print(
            f"  {course} | {label}: "
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


def choose_items(repo_root: Path, courses: dict[str, Path]) -> list[PlanItem]:
    course_names = list(courses.keys())
    print("\n可选课程列表:")
    for idx, name in enumerate(course_names, 1):
        print(f"  {idx}. {name}")
    while True:
        raw = input("请选择课程编号（如 1,3 或 all）: ")
        try:
            course_indices = parse_selection(raw, len(course_names))
            if course_indices:
                break
        except Exception as err:
            print(f"输入无效: {err}")

    plan: list[PlanItem] = []
    for course_idx in course_indices:
        course = course_names[course_idx - 1]
        excel = courses[course]
        labels_map, labels_df = discover_labels(excel)
        labels = list(labels_map.keys())
        print(f"\n选择提交序号: {course}")
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
            course=course,
            labels=selected_labels,
            labels_df=labels_df,
            published_cutoffs=load_published_cutoffs(repo_root, course),
        )
        plan.append(
            PlanItem(
                course=course,
                excel=excel,
                labels=selected_labels,
                cutoff_policy=cutoff_policy,
                manual_cutoffs=manual_cutoffs,
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
        "--excel",
        str(item.excel),
    ]
    for label in item.labels:
        cmd.extend(["--label", label])
    cmd.extend(["--cutoff-policy", item.cutoff_policy])
    for label, cutoff in item.manual_cutoffs.items():
        cmd.extend(["--cutoff", f"{label}={cutoff}"])
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
        print(f"\n开始处理: {item.course} labels={', '.join(item.labels)}")
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
            print(f"处理失败: {item.course}")
            return proc.returncode
    return 0


def prompt_source_cleanup(python_exe: Path, repo_root: Path, config_path: Path, plan: list[PlanItem]) -> int:
    print("\n源附件清理默认跳过。可选模式: skip / dry-run / apply")
    raw = input("是否清理企业微信本地同步源附件？[skip/dry-run/apply]: ").strip().lower()
    if raw in {"", "skip", "s", "n", "no"}:
        print("已跳过源附件清理。")
        return 0
    if raw in {"dry-run", "dry", "d"}:
        return run_extracts(python_exe, repo_root, config_path, plan, cleanup_mode="dry-run", cleanup_only=True)
    if raw in {"apply", "a"}:
        confirm = input("确认删除源附件请输入 APPLY: ").strip()
        if confirm != "APPLY":
            print("未输入 APPLY，已取消源附件清理。")
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
    parser.add_argument("--config", default=str(repo_root / "config" / "local.config.json"))
    parser.add_argument("--no-auto-push", dest="auto_push", action="store_false")
    parser.add_argument("--no-git", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    config_path = Path(args.config).resolve()
    courses_dir = repo_root / "config"
    courses = discover_courses(courses_dir)
    if not courses:
        print("未发现新模型 Excel。")
        return 1
    plan = choose_items(repo_root, courses)
    print("\n执行计划:")
    for item in plan:
        print(f"- {item.course}: {', '.join(item.labels)} | cutoff={item.cutoff_policy}")
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
