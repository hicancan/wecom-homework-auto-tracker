# WeCom Homework Auto Tracker

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=111827)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

课程作业自动采集、统计与可视化看板。  
面向企业微信微盘作业提交流程，支持多课程、课程路由分享、隐私保护（仅学号）。

</div>

## Features

- 自动识别课程 Excel，按作业批次汇总提交情况
- 输出课程级 JSON 到前端，开箱即用
- 前端支持课程路由与分享链接
- 严格路由参数校验（无效课程/作业直接报错）
- 隐私保护：Web 数据仅保留学号，不包含姓名
- 本地路径全部通过 `config/local.config.json` 管理

## Project Structure

```text
local/                 # Python 数据提取脚本
webapp/                # React + Vite 前端看板
config/                # 本地配置目录（默认不入库，仅保留模板）
out/                   # 本地输出目录（不入库）
```

## Quick Start

### 1) Clone

```bash
git clone https://github.com/hicancan/wecom-homework-auto-tracker.git
cd wecom-homework-auto-tracker
```

### 2) Prepare Local Config

复制模板并填写你的本地路径：

```bash
copy config\config.template.json config\local.config.json
```

`config/local.config.json` 关键项：

- `courses_dir`: 课程 Excel 目录
- `attachments_root`: 企业微信微盘根目录
- `students`: 学生名单 JSON
- `out_root`: 本地导出目录
- `web_data_root`: 前端数据目录
- `course_index`: 课程索引文件

### 3) Generate Data

```bash
python local/extract_homework.py --config config/local.config.json --course "你的课程名"
```

### 4) Run Web App

```bash
cd webapp
npm install
npm run dev
```

## Privacy Guarantee

本项目默认将前端展示数据限制为“学号级别”：

- `已交名单`: 学号数组
- `未交名单`: 学号数组

不会在 `webapp/public/data/*.json` 中写入姓名字段。

## Routing Design

- 首页：`#/`
- 课程页：`#/course/:courseName`
- 作业参数：`?hw=第N次`

示例：

```text
#/course/算法分析与设计B240401-03?hw=第2次
```

## Screenshots

- 首页：课程入口与仓库链接
- 课程页：作业提交率、班级明细、学号级未交名单

## Roadmap

- [ ] 增加端到端测试
- [ ] 增加课程 slug 映射策略
- [ ] 增加 CI 数据合规检查（禁止姓名泄漏）

## Contributing

欢迎提 Issue / PR。提交前建议执行：

```bash
cd webapp
npm run build
```

## License

MIT
