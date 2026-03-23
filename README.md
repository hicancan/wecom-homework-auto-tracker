# WeCom Homework Auto Tracker

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111827)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4.2-38B2AC?logo=tailwind-css&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

课程作业自动采集、统计与可视化看板。  
面向企业微信微盘（WeDrive）或腾讯文档等收集的作业，提供全自动化比对、文件整理及静态站点部署方案。

</div>

## 💡 核心特性 (Features)

本项目旨在解决教学过程中“查收作业”的痛点。当学生通过收集表或共享文件夹提交作业到企业微信微盘后：

- 🤖 **自动比对提取**：利用 Python 脚本读取包含提交记录的 Excel，与本地同步的微盘文件夹进行精准比对，提取最新的有效提交。
- 📦 **自动重命名与防冲突**：自动将杂乱的附件按 `学号+姓名.扩展名` 格式重命名并分类存放。
- 📊 **多维数据统计**：自动按班级计算应交、已交、未交人数及提交率，输出标准化的 JSON 结构。
- 🌐 **现代可视化看板**：基于 React 19 + TailwindCSS 4 的现代化响应式前端，直观展示各项统计数据。
- 🔒 **严格隐私保护**：前端展示数据（已交/未交名单）**仅包含学号**，从源头杜绝学生姓名等敏感信息在公网泄漏。
- 🚀 **GitHub Actions 自动化部署**：推送统计数据到 `main` 分支后，自动触发 CI/CD 构建并部署至 GitHub Pages，并支持 Cloudflare 缓存清理。

## 📂 项目结构 (Project Structure)

```text
├── local/               # Python 数据提取与处理脚本核心目录
│   └── extract_homework.py 
├── webapp/              # 现代化 Web 看板 (React 19 + Vite + Tailwind 4)
│   ├── public/data/     # [存放 Python 生成的各种 JSON 统计数据集]
│   └── src/             # 前端代码
├── config/              # 本地配置文件目录（Git 忽略配置内容，仅保留模板）
│   ├── config.template.json
│   └── students.json    # 学生名单数据样例/配置
├── out/                 # 本地导出的已重命名整理好的作业文件（Git 忽略）
└── .github/workflows/   # GitHub Actions 自动化部署脚本 pages.yml
```

## 🚀 快速开始 (Quick Start)

### 1) 准备工作 (Prerequisites)
- **Python 3.10+**，并安装依赖：`pip install pandas openpyxl requests`
- **Node.js 24+** (用于本地调试前端)
- **微盘本地同步**：请确保企业微信微盘的“收集的文件”已通过微盘客户端同步到本地电脑。

### 2) 获取项目并配置环境

```bash
git clone https://github.com/hicancan/wecom-homework-auto-tracker.git
cd wecom-homework-auto-tracker

# 复制配置文件模板
copy config\config.template.json config\local.config.json
```

编辑 `config/local.config.json`，正确配置以下路径：
- `courses_dir`: 存放课程登记信息的 Excel 所在目录。
- `attachments_root`: 电脑上企业微信微盘同步根目录。
- `students`: 花名册（JSON 格式，包含姓名、学号、班级字段）。

### 3) 提取与整理作业
在本地运行 Python 脚本，将会在 `out/` 下输出重命名好的作业文件，同时在 `webapp/public/data/` 自动生成看板所需的追踪与统计 JSON 数据。

```bash
python local/extract_homework.py --course "你的课程名"
```

### 4) 本地预览看板 (Local Preview)

```bash
cd webapp
npm install
npm run dev
```

### 5) 自动化公开发布 (Deploy to GitHub Pages)
确认本地提取的合并 JSON 数据（位于 `webapp/public/data/` 和 `webapp/public/courses.json`）正确无误后，只需提交代码并推送到 GitHub：

```bash
git add webapp/public/
git commit -m "chore: update homework stats"
git push origin main
```

项目的 **GitHub Actions** (`pages.yml`) 将会侦测到 WebApp 目录的改动并自动构建，将安全的静态网站部署至 GitHub Pages 供学生查看状态。

## 🛡️ 数据合规与隐私保证

本项目在数据传输到前端看板前，进行了严格的安全脱敏过滤：
- **JSON 提取层**：生成的所有 `[已交名单]`与`[未交名单]`数组剔除任何关联的姓名信息。
- **页面路由级**：支持独立课程的 URL 分发（如 `#/course/课程名?hw=第2次`），错误/缺失的参数直接阻断渲染。

## 🤝 参与贡献 (Contributing)

如果你有改进想法，欢迎提交 Issue 或 Pull Request。
在提交涉及前端变更的 PR 前，建议在本地执行构建检查：

```bash
cd webapp
npm run build
```

## 📄 开源许可证 (License)

基于 **MIT License** 开源，详见 `LICENSE` 文件。
