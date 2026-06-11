from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = REPO_ROOT / "local"
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

from publish_plan import PlanItem, build_extract_cmd, choose_items, discover_collections  # noqa: E402
from registration import register_unregistered_excels  # noqa: E402


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"配置不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"配置必须是 JSON 对象: {path}")
    return data


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
    parser = argparse.ArgumentParser(description="新模型增量收集交互入口")
    parser.add_argument("--config", default=str(REPO_ROOT / "config" / "config.json"))
    parser.add_argument("--no-auto-push", dest="auto_push", action="store_false")
    parser.add_argument("--no-git", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        fallback = REPO_ROOT / "config" / "local.config.json"
        config_path = fallback if fallback.exists() else config_path
    cfg = load_config(config_path)
    cfg = register_unregistered_excels(REPO_ROOT, config_path, cfg)
    collections = discover_collections(REPO_ROOT, cfg)
    if not collections:
        print("未发现可提取的收集表 Excel。")
        return 1

    plan = choose_items(REPO_ROOT, collections)
    print("\n执行计划:")
    for item in plan:
        window = ""
        if item.publish_mode == "makeup-window":
            window = f" | window={item.makeup_window_start or 'cutoff'} -> {item.makeup_window_end}"
        print(f"- {item.collection_id}: {', '.join(item.labels)} | cutoff={item.cutoff_policy} | mode={item.publish_mode}{window}")
    if input("确认执行？[y/N]: ").strip().lower() != "y":
        print("已取消。")
        return 1

    code = run_extracts(Path(sys.executable), REPO_ROOT, config_path, plan)
    if code != 0:
        return code
    cleanup_code = prompt_source_cleanup(Path(sys.executable), REPO_ROOT, config_path, plan)
    if cleanup_code != 0:
        return cleanup_code
    if args.no_git:
        print("已按参数跳过 git。")
        return 0
    git_commit_public(REPO_ROOT, args.auto_push)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
