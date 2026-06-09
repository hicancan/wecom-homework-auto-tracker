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

```
学生微信提交 → 企业微信收集表 → Excel 导出
                                   ↓
                          extract_homework.py
                    ┌──────────┼──────────┐
                    ↓          ↓          ↓
              版本归档      统计报告    ZIP 打包
                    │          │          │
                    └──────────┼──────────┘
                               ↓
                      GitHub Pages 看板
```

## 核心特性

- **增量版本归档** — 每次收集追加版本，文件变化存 `_versions/`，旧版本永不丢失
- **双发布模式** — `cutoff`（截止模式，超时=未提交）或 `makeup-window`（补交窗口，窗口内补交标蓝）
- **后缀校验** — 签约 `.doc/.docx`，学生传了 `.pdf` 自动标记无效
- **Fail-Fast 名单校验** — 收集前扫描 Excel 填写人，不在名单内立即阻断并报告
- **Serverless 部署** — 纯静态 JSON + React PWA，GitHub Pages 零运维成本
- **四色状态体系** — 绿=已提交 / 蓝=已补交 / 红=未提交 / 黄=后缀无效

## 快速开始

```powershell
# 1. 复制配置模板
Copy-Item .\config\config.template.json .\config\local.config.json

# 2. 编辑 local.config.json，填入 Excel 路径、微盘同步路径、学生名单

# 3. 交互式收集（推荐）
uv run python .\scripts\run_extract_interactive.py --config .\config\local.config.json

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

## 归档分层

```
out/collections/<collection_id>/
├── archive_manifest.json     ← 权威真相源（所有版本索引 + SHA256）
├── files/
│   ├── _versions/            ← 不可变版本仓库（审计用，永不删除）
│   └── current/              ← 当前激活版本快照（每次收集重建）
├── history/                  ← 被覆盖的旧文件（只增不删）
├── zip/                      ← 按提交序号打包
└── stats/                    ← 统计报告（与 web 同步）
```

## Tech Stack

| 层 | 技术 |
|------|------|
| 离线管线 | Python 3.12 + pandas + openpyxl |
| 前端 | React 19 + TypeScript 5.9 + Tailwind CSS |
| 构建 | Vite + Rolldown |
| 部署 | GitHub Pages + PWA（Service Worker 离线可用） |
| 数据 | 静态 JSON（`webapp/public/data/`） |
| 测试 | pytest（16 用例） |

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
| 🔴 未提交 | 未交或文件丢失 | 未提交 / WeDrive 源不可用 |
| 🟡 后缀无效 | 格式错误 | 文件后缀不符合提交内容约定 |

## License

[GNU Affero General Public License v3.0](LICENSE) — 自由使用、修改、分发。网络部署须公开源码。

---

<div align="center">
  <sub>Built for NJUPT</sub>
</div>
