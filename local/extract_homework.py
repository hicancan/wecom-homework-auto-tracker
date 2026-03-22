# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pandas",
#     "openpyxl",
#     "requests",
# ]
# ///
import os
import shutil
import json
import argparse
import pandas as pd
import requests
import re


PROJECT_NAME = "算法分析与设计B240401-03"

def get_exact_filename_from_url(url: str) -> str:
    """访问腾讯微盘的分享链接，从网页 <title> 提取本地被同步存下的精确文件名"""
    url = url.strip()
    # 如果 Excel 直接存储的是全名而不是 URL（这经常在某些字段配置下发生），直接返回它
    if not url.startswith('http'):
        return url
        
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        match = re.search(r'<title>(.*?)</title>', r.text)
        if match:
            title = match.group(1).strip()
            # 过滤掉偶尔出现的 "腾讯文档" 或 "企业微信" 默认title
            if title and "微信" not in title and "腾讯" not in title:
                return title
    except Exception as e:
        print(f"  [!] 获取URL文件名失败: {e}")
    return ""


def normalize_name(name: str) -> str:
    """统一姓名格式，减少空格差异导致的匹配失败。"""
    return re.sub(r"\s+", "", str(name)).strip()


def build_target_homework(homework: str | int) -> str:
    """将用户输入标准化为“第N次”格式。"""
    hw = str(homework).strip()
    if hw.isdigit():
        return f"第{hw}次"
    match = re.search(r"(\d+)", hw)
    if match:
        return f"第{match.group(1)}次"
    return hw


def load_students_by_class(students_json_path: str) -> dict[str, list[str]]:
    if not os.path.exists(students_json_path):
        raise FileNotFoundError(f"找不到学生名单文件: {students_json_path}")

    with open(students_json_path, "r", encoding="utf-8") as f:
        students = json.load(f)

    by_class: dict[str, list[str]] = {}
    for item in students:
        class_name = str(item.get("班级", "")).strip()
        student_name = normalize_name(item.get("姓名", ""))
        if not class_name or not student_name:
            continue
        by_class.setdefault(class_name, []).append(student_name)

    return by_class

def extract_latest_homework(
    excel_path: str,
    attachments_dir: str,
    output_dir: str,
    students_json_path: str,
    target_homework: str = "第1次",
):
    print(f">>> 开始处理：目标作业=[{target_homework}]")
    
    if not os.path.exists(excel_path):
        print(f"错误: 找不到Excel文件 {excel_path}")
        return
        
    students_by_class = load_students_by_class(students_json_path)
    all_classes = sorted(students_by_class.keys())
    if not all_classes:
        print("错误: 学生名单为空，无法统计提交情况。")
        return

    df = pd.read_excel(excel_path)
    
    col_name = next((c for c in df.columns if '填写人' in c), None)
    col_time = next((c for c in df.columns if '填写时间' in c), None)
    col_hw = next((c for c in df.columns if '本次提交的是哪次作业' in c), None)
    col_file = next((c for c in df.columns if '请上传作业文件' in c), None)
    
    if not all([col_name, col_time, col_hw, col_file]):
        print("错误: 无法在Excel中找到需要的列。请检查文件内容。")
        return

    df_hw = df[df[col_hw].astype(str).str.contains(target_homework, na=False)].copy()
    if df_hw.empty:
        print(f"未找到属于 {target_homework} 的提取记录")
        return
        
    df_hw[col_time] = pd.to_datetime(df_hw[col_time])
    df_hw["_name_norm"] = df_hw[col_name].astype(str).map(normalize_name)
    df_latest = df_hw.sort_values(by=col_time).drop_duplicates(subset=[col_name], keep='last')
    latest_by_name = {normalize_name(r[col_name]): r for _, r in df_latest.iterrows()}
    
    print(f"共找到 {len(df_latest)} 位同学的最新提交记录。")
    
    if attachments_dir and os.path.isdir(attachments_dir):
        if os.path.isdir(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)
        for class_name in all_classes:
            os.makedirs(os.path.join(output_dir, class_name), exist_ok=True)

        files_in_dir = os.listdir(attachments_dir)
        
        stat = {
            "作业": target_homework,
            "课程": PROJECT_NAME,
            "总班级数": len(all_classes),
            "班级统计": {},
        }

        total_submit = 0
        total_expected = 0

        for class_name in all_classes:
            class_students = students_by_class[class_name]
            submitted = []
            not_submitted = []

            for student_name in class_students:
                row = latest_by_name.get(student_name)
                if row is None:
                    not_submitted.append(student_name)
                    continue

                person_name = str(row[col_name])
                file_url = str(row[col_file])
                target_file = get_exact_filename_from_url(file_url)

                if not target_file:
                    print(f"[{person_name}] 无法从链接提取确切文件名，尝试在目录中模糊搜索...")
                    matched = [f for f in files_in_dir if person_name in f or student_name in f]
                    if matched:
                        matched.sort(
                            key=lambda x: os.path.getmtime(os.path.join(attachments_dir, x)),
                            reverse=True,
                        )
                        target_file = matched[0]
                    else:
                        print(f"  彻底未找到 [{person_name}] 的可用附件！")
                        not_submitted.append(student_name)
                        continue

                if target_file not in files_in_dir:
                    print(f"[{person_name}] Excel指向的文件名 '{target_file}' 在同步文件夹中不存在！")
                    not_submitted.append(student_name)
                    continue

                src_path = os.path.join(attachments_dir, target_file)
                dst_path = os.path.join(output_dir, class_name, target_file)

                shutil.copy2(src_path, dst_path)
                submitted.append(student_name)
                print(f"√ [{class_name}] 复制精准匹配: {person_name} -> {target_file}")

            expected_count = len(class_students)
            submit_count = len(submitted)
            total_expected += expected_count
            total_submit += submit_count

            stat["班级统计"][class_name] = {
                "应交人数": expected_count,
                "已交人数": submit_count,
                "未交人数": len(not_submitted),
                "提交率": round((submit_count / expected_count) if expected_count else 0, 4),
                "已交名单": submitted,
                "未交名单": not_submitted,
            }

        stat["汇总"] = {
            "应交总人数": total_expected,
            "已交总人数": total_submit,
            "未交总人数": total_expected - total_submit,
            "总提交率": round((total_submit / total_expected) if total_expected else 0, 4),
        }

        stat_path = os.path.join(output_dir, "stats.json")
        with open(stat_path, "w", encoding="utf-8") as f:
            json.dump(stat, f, ensure_ascii=False, indent=2)

        print(f"\n处理完成！输出目录: {output_dir}")
        print(f"统计已写入: {stat_path}")
    else:
        print("未提供有效的附件目录，仅输出通过 Excel 筛选得到的最新名单：")
        for _, row in df_latest.iterrows():
            print(f"- {row[col_name]} (提交时间: {row[col_time]})")


def parse_args() -> argparse.Namespace:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)

    default_excel = os.path.join(repo_root, "config", f"{PROJECT_NAME}.xlsx")
    default_students = os.path.join(repo_root, "config", "B240401_to_B240403_students.json")
    default_homework = "1"

    parser = argparse.ArgumentParser(description="按作业次数提取最新提交并按班级打包。")
    parser.add_argument("--homework", default=default_homework, help="作业次数，如 1、2 或 第2次")
    parser.add_argument("--excel", default=default_excel, help="收集结果 Excel 文件路径")
    parser.add_argument("--attachments", default=r"C:\Users\user\Documents\WXWork\0000000000000000\WeDrive\南京邮电大学\我的文件\算法分析与设计B240401-03收集的文件", help="同步附件目录")
    parser.add_argument("--students", default=default_students, help="学生名单 JSON 路径")
    parser.add_argument(
        "--output",
        default="",
        help="输出目录；不传时默认 out/算法分析与设计B240401-03第N次作业",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    target_hw = build_target_homework(args.homework)

    output_dir = args.output.strip() if args.output.strip() else ""
    if not output_dir:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(script_dir)
        output_dir = os.path.join(repo_root, "out", f"{PROJECT_NAME}{target_hw}作业")

    extract_latest_homework(
        excel_path=args.excel,
        attachments_dir=args.attachments,
        output_dir=output_dir,
        students_json_path=args.students,
        target_homework=target_hw,
    )
