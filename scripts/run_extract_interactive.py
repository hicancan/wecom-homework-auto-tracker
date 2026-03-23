#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class PlanItem:
    course: str
    excel: Path
    from_order: int
    to_order: int


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"配置文件格式错误，应为 JSON 对象: {path}")
    return data


def resolve_path(repo_root: Path, text: str) -> Path:
    raw = (text or "").strip()
    if not raw:
        return Path()
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    return p


def discover_courses(courses_dir: Path) -> list[Path]:
    if not courses_dir.exists():
        raise FileNotFoundError(f"课程目录不存在: {courses_dir}")
    files = [
        p
        for p in sorted(courses_dir.iterdir())
        if p.is_file() and p.suffix.lower() in {".xlsx", ".xls"} and not p.name.startswith("~$")
    ]
    if not files:
        raise FileNotFoundError(f"课程目录下没有可用 Excel: {courses_dir}")
    return files


def parse_selection(text: str, max_index: int) -> list[int]:
    raw = (text or "").strip()
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    if raw.startswith("ï»¿"):
        raw = raw[3:]
    raw = raw.lower().replace("，", ",").replace("、", ",")
    if not raw:
        raise ValueError("未输入课程编号。")
    if raw == "all":
        return list(range(1, max_index + 1))

    picked: set[int] = set()
    for part in [x.strip() for x in raw.split(",") if x.strip()]:
        part = re.sub(r"^[^0-9a-z]+", "", part)
        if not part:
            continue
        if "-" in part:
            seg = part.split("-", 1)
            if len(seg) != 2 or (not seg[0].isdigit()) or (not seg[1].isdigit()):
                raise ValueError(f"无法解析课程选择片段: '{part}'")
            start, end = int(seg[0]), int(seg[1])
            if start > end:
                raise ValueError(f"区间 '{part}' 非法（起点大于终点）。")
            for i in range(start, end + 1):
                if i < 1 or i > max_index:
                    raise ValueError(f"编号 '{i}' 超出范围 1-{max_index}。")
                picked.add(i)
            continue
        if part.isdigit():
            i = int(part)
            if i < 1 or i > max_index:
                raise ValueError(f"编号 '{i}' 超出范围 1-{max_index}。")
            picked.add(i)
            continue
        raise ValueError(f"无法解析课程选择片段: '{part}'")
    return sorted(picked)


def read_positive_int(prompt: str) -> int:
    while True:
        raw = input(prompt).strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("请输入正整数。")


def print_plan(items: list[PlanItem]) -> None:
    print("\n执行预览：")
    if not items:
        print("(空)")
        return
    max_course = max(len(i.course) for i in items)
    max_excel = max(len(str(i.excel)) for i in items)
    header = f"{'Course'.ljust(max_course)}  {'Excel'.ljust(max_excel)}  From  To"
    print(header)
    print("-" * len(header))
    for item in items:
        print(
            f"{item.course.ljust(max_course)}  {str(item.excel).ljust(max_excel)}  "
            f"{str(item.from_order).rjust(4)}  {str(item.to_order).rjust(2)}"
        )


def run_extract(python_exe: Path, repo_root: Path, item: PlanItem) -> int:
    extract_script = repo_root / "local" / "extract_homework.py"
    cmd = [
        str(python_exe),
        str(extract_script),
        "--excel",
        str(item.excel),
        "--from",
        str(item.from_order),
        "--to",
        str(item.to_order),
    ]
    print(f"\n开始处理: {item.course} --from {item.from_order} --to {item.to_order}")
    proc = subprocess.run(cmd, cwd=repo_root)
    if proc.returncode == 0:
        print(f"处理完成: {item.course}")
    else:
        print(f"处理失败: {item.course}")
    return proc.returncode


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def auto_publish(repo_root: Path) -> None:
    run(["git", "add", "webapp/public"], cwd=repo_root)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", "webapp/public"],
        cwd=repo_root,
    )
    if staged.returncode == 0:
        print("\nGitHub 提交步骤：webapp/public 无变更，跳过提交和推送。")
        return

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root).stdout.strip()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"chore(data): update homework stats ({timestamp})"

    print("\nGitHub 提交步骤：")
    run(["git", "commit", "-m", message], cwd=repo_root)
    run(["git", "push", "origin", branch], cwd=repo_root)
    print(f"已提交并推送到 origin/{branch}")


def resolve_python(repo_root: Path, python_arg: str) -> Path:
    if python_arg.strip():
        p = resolve_path(repo_root, python_arg)
        if not p.exists():
            raise FileNotFoundError(f"指定的 Python 可执行文件不存在: {p}")
        return p

    venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python

    if sys.executable:
        return Path(sys.executable)

    raise FileNotFoundError("未找到 Python 可执行文件。")


def main() -> int:
    parser = argparse.ArgumentParser(description="交互式作业提取（CMD 入口）。")
    parser.add_argument("--config", default="", help="配置文件路径，默认 config/local.config.json")
    parser.add_argument("--courses-dir", default="", help="课程 Excel 目录")
    parser.add_argument("--python", default="", help="Python 可执行文件路径")
    parser.set_defaults(auto_push=True)
    parser.add_argument("--auto-push", dest="auto_push", action="store_true", help="执行成功后自动 commit + push")
    parser.add_argument("--no-auto-push", dest="auto_push", action="store_false", help="执行成功后不提交推送")
    parser.add_argument("--no-git", action="store_true", help="跳过 git 提交步骤")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    config_path = resolve_path(repo_root, args.config) if args.config.strip() else (repo_root / "config" / "local.config.json")
    config = load_config(config_path)

    courses_dir_text = args.courses_dir.strip() or str(config.get("courses_dir", "config"))
    courses_dir = resolve_path(repo_root, courses_dir_text)
    python_exe = resolve_python(repo_root, args.python)
    courses = discover_courses(courses_dir)

    print(f"\n可选课程列表（来源: {courses_dir}）")
    for idx, file in enumerate(courses, start=1):
        print(f"[{idx}] {file.stem}")

    selected_indexes: list[int]
    while True:
        raw = input("\n请选择课程编号（如 1,3-4 或 all）: ")
        try:
            selected_indexes = parse_selection(raw, len(courses))
            break
        except ValueError as err:
            print(err)

    plan: list[PlanItem] = []
    for idx in selected_indexes:
        file = courses[idx - 1]
        print(f"\n配置区间: {file.stem}")
        from_order = read_positive_int("  --from: ")
        to_order = read_positive_int("  --to: ")
        while from_order > to_order:
            print("  from 不能大于 to，请重新输入。")
            from_order = read_positive_int("  --from: ")
            to_order = read_positive_int("  --to: ")
        plan.append(
            PlanItem(
                course=file.stem,
                excel=file.resolve(),
                from_order=from_order,
                to_order=to_order,
            )
        )

    print_plan(plan)
    confirm = input("\n确认执行以上计划？[y/N]: ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("已取消执行。")
        return 0

    failed: list[str] = []
    for item in plan:
        code = run_extract(python_exe=python_exe, repo_root=repo_root, item=item)
        if code != 0:
            failed.append(item.course)

    if failed:
        print("\n以下课程处理失败：")
        for name in failed:
            print(f"- {name}")
        return 1

    print("\n全部课程处理完成。")
    if args.no_git:
        print("已按参数 --no-git 跳过提交。")
        return 0

    if args.auto_push:
        auto_publish(repo_root)
        return 0
    print("已按参数 --no-auto-push 跳过提交推送。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
