<div align="center">

<img src="webapp/public/favicon.svg" width="80" />

# WeCom Collection Tracker

**企业微信收集表 → 增量归档 → 公开追踪看板**

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-FFD43B.svg)](https://www.python.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-blue.svg)](https://www.typescriptlang.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)
[![PWA](https://img.shields.io/badge/PWA-Supported-orange.svg)](https://vite-pwa-org.netlify.app/)
[![GitHub Pages](https://img.shields.io/badge/deploy-GitHub%20Pages-4F46E5)](https://pages.github.com/)

[**在线看板**](https://homework.hicancan.top) · [**运维手册**](docs/OPERATIONS.md)

</div>

---

## 这是什么

教师用**企业微信收集表**收作业。学生微信提交后，本系统将收集表导出为 Excel，匹配本地微盘同步目录中的附件，做**增量版本归档**，最终生成一个**静态公开看板**，展示每个学生的提交状态（已提交 / 已补交 / 未提交 / 后缀无效）。

```mermaid
flowchart LR
    A[学生微信提交] --> B[企业微信收集表]
    B --> C[Excel 导出]
    C --> D[extract_homework.py]
    D --> E[版本归档 _versions/]
    D --> F[统计报告 stats/]
    D --> G[ZIP 打包 zip/]
    E --> H[archive_manifest.json]
    F --> H
    H --> I[GitHub Pages 看板]
```

## 核心特性

- **增量版本归档** — 每次收集追加版本，文件变化存 `_versions/`，旧版本永不丢失
- **双发布模式** — `cutoff`（截止模式，超时=未提交）或 `makeup-window`（补交窗口，窗口内补交标蓝）
- **后缀校验** — 签约 `.doc/.docx`，学生传了 `.pdf` 自动标记无效
- **Fail-Fast 名单校验** — 收集前扫描 Excel 填写人，不在名单内立即阻断并报告
- **Serverless 部署** — 纯静态 JSON + React PWA，GitHub Pages 与 EdgeOne Pages 双发布
- **四色状态体系** — 绿=已提交 / 蓝=已补交 / 红=未提交 / 黄=后缀无效

## 快速开始

```powershell
# 1. 复制配置模板
Copy-Item .\config\config.template.json .\config\local.config.json

# 2. 编辑 local.config.json，填入微盘同步路径、学生名单

# 3. 交互式收集（推荐）
uv run python .\scripts\run_extract_interactive.py --config .\config\local.config.json

# 未注册的新模型 Excel 会在交互入口中自动提示注册，并建议稳定 collection_id

# 4. 或命令行精确控制
uv run python .\local\extract_homework.py `
  --config .\config\local.config.json `
  --collection-id algorithm-design-homework-b240401-03-sophomore-spring `
  --label 第1次 --label 第2次 `
  --cutoff-policy keep `
  --publish-mode cutoff
```

## 数据模型

**收集表标题**强制格式 `主题[对象][周期]`：
```
算法分析与设计作业[B240401-03][大二下]
人工智能导论及其Python应用实践实验[B240402][大二下]
```

**提交内容**强制格式 `内容名(.ext/.ext)`：
```
作业(.doc/.docx)
实验报告(.doc/.docx)
```

**唯一业务键**：`学号 + 提交序号 + 提交内容`

## 新增收集表

新增企业微信收集表时，只要把导出的 Excel 放进 `collections_dir`，并保证文件名等于标题：

```text
数学建模期末大作业[B240402][大二下].xlsx
```

随后运行交互脚本。系统会解析标题、读取 `提交序号 / 提交内容`，并建议小写 ASCII `collection_id`，例如：

```text
math-modeling-final-b240402-sophomore-spring
```

确认后写入本地 `config/local.config.json`。`提交内容` 不允许为空，也不再支持配置默认值；空值会直接失败，避免脏数据进入归档。

## 归档分层

```mermaid
graph TD
    subgraph 不可变
        A[archive_manifest.json] --> B[_versions/]
        B --> C[history/]
    end
    subgraph 可重建
        D[current/] --> E[zip/]
        E --> F[stats/]
    end
    A --> D
```

| 层 | 属性 | 说明 |
|------|------|------|
| `archive_manifest.json` | 不可变 | 权威真相源，所有版本索引 + SHA256 |
| `_versions/` | 不可变 | 文件变化时存新版本，永不删除 |
| `history/` | 不可变 | 被覆盖的旧文件，只增不删 |
| `current/` | 可重建 | 最新版本快照，每次收集重建 |
| `zip/` | 可重建 | 按提交序号打包 |
| `stats/` | 可重建 | 统计报告，与 web 同步 |

## 界面

![主页](docs/homepage.png)

![详情页](docs/detail.png)

## Tech Stack

| 层 | 技术 |
|------|------|
| 离线管线 | Python 3.12 + pandas + openpyxl |
| 前端 | React 19 + TypeScript 5.9 + Tailwind CSS |
| 构建 | Vite + Rolldown |
| 部署 | GitHub Pages + EdgeOne Pages + PWA（Service Worker 离线可用） |
| 数据 | 静态 JSON（`webapp/public/data/`） |
| 测试 | pytest + Vitest |

## 项目结构

```
wecom-homework-auto-tracker/
├── config/             # Excel、学生名单、本地配置（gitignored）
├── local/              # Python 离线管线
│   ├── extract_homework.py   # 主入口
│   ├── archive.py            # 增量归档引擎
│   ├── stats.py              # 统计计算 + 双发布模式
│   └── contract.py           # 数据契约 + 校验
├── scripts/            # 交互式入口
├── webapp/             # React 前端
│   ├── src/
│   │   ├── pages/      # 主页 + 收集表详情页
│   │   └── components/ # 状态卡片、进度条、图例
│   └── public/data/    # 公开数据（git tracked）
├── tests/              # pytest 测试
├── docs/               # 文档
└── out/                # 本地归档产物（gitignored）
```

## 状态口径

| 颜色 | 状态 | 条件 |
|------|------|------|
| 🟢 已提交 | 截止内有效提交 | 截止前文件存在且后缀正确 |
| 🔵 已补交 | 补交窗口内提交 | 截止后、窗口内有效提交 |
| 🔴 未提交 | 未达标 | 截止口径内没有有效提交 |
| 🟡 后缀无效 | 格式错误 | 文件后缀不符合提交内容约定 |

## License

[GNU Affero General Public License v3.0](LICENSE) — 自由使用、修改、分发。网络部署须公开源码。

---

<div align="center">
  <sub>Built for NJUPT</sub>
</div>
