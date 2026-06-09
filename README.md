# WeCom Collection Tracker

企业微信微盘收集表的本地增量归档与在线看板系统。

核心原则：

- 新表单契约是唯一入口：`主题[对象][周期可选] + 提交序号 + 提交内容 + 请上传对应文件`
- 本地归档是权威基线：企业微信同步目录只作为增量输入，云端源文件删除不会让历史收包回退为缺失。
- 唯一业务键：`学生 + 提交序号 + 提交内容 -> 最后一次对应文件`
- 单文件和多文件统一建模：即使只有一个文件，也必须填写 `提交内容`。

## 表单契约

收集表标题只允许两种格式：

```text
主题[对象]
主题[对象][周期]
```

示例：

```text
人工智能导论及其Python应用实践实验[B240402][大二下]
算法分析与设计作业[B240401-03][大二下]
算法分析与设计实验[B240401-03][大二下]
```

Excel 必须包含这些列：

- `填写人`
- `所在部门`
- `填写时间`
- `提交序号`
- `提交内容`
- `请上传对应文件`
- `用户类型`

`提交内容` 必须绑定允许后缀，格式为：

```text
内容名(.ext/.ext)
```

示例：

```text
实验报告(.doc/.docx)
作业(.doc/.docx)
源代码(.zip)
```

脚本会 fail-fast：标题、列名、空 `提交序号`、空 `提交内容`、非法后缀契约都会直接失败。上传文件后缀不在 `提交内容` 契约内时，记录为无效附件，不计入提交率。

## 本地归档结构

```text
out/<主题[对象][周期]>/
  files/
    _versions/
      <entry-id>/
        <version>/
          <学号姓名.ext>
    <提交序号>/
      <提交内容名>/
        <班级>/
          <学号姓名.ext>
  zip/
    <提交序号>.zip
  stats/
    <提交序号>.json
  archive_manifest.json
  collection_summary.json
```

增量规则：

- `archive_manifest.json` 是本地权威索引，每个业务键保存不可变 `versions[]`。
- 企业微信同步目录有同一业务键的新提交时，追加新版本，并更新 `files/<提交序号>/...` 最新有效镜像。
- 企业微信同步目录源文件已删除，但归档里已有有效版本时，继续保留本地归档。
- 最新提交后缀无效时，该业务键统计为无效，不用旧有效版本充当本次有效提交。
- 已发布提交序号会保留 `统计截止时间`；看板和 zip 只统计截止时间之前的版本，避免 Excel 里的后续补交污染旧云端面板口径。
- 截止后的记录进入本地归档和 `补交状态`，前端只给截止时未达标的学生换色，不单独展示补交名单。
- 每个 `提交序号` 生成一个 zip，zip 内固定为 `提交内容/班级/学号姓名.ext`。

## 配置

复制模板：

```powershell
Copy-Item .\config\config.template.json .\config\local.config.json
```

主要字段：

- `courses_dir`: 新模型 Excel 所在目录。
- `attachments_root`: 企业微信微盘同步根目录。
- `attachments`: 临时覆盖单个附件目录，通常留空。
- `students`: 主学生名单 JSON。
- `other_students`: 重修、补修等其他学生名单 JSON。
- `zip_enabled`: 是否生成 zip。
- `out_root`: 本地归档根目录。
- `web_data_root`: 前端公开数据目录。
- `course_index`: 前端课程总索引。
- `course_classes`: 可选班级作用域缓存和锁定配置。

学生名单格式：

```json
[
  { "班级": "B240401", "学号": "B24040101", "姓名": "张三" },
  { "班级": "B240402", "学号": "B24040201", "姓名": "李四" }
]
```

## 运行

交互式运行：

```powershell
.\scripts\run_extract_interactive.cmd
```

命令行运行：

```powershell
uv run python .\local\extract_homework.py `
  --excel ".\config\算法分析与设计作业[B240401-03][大二下].xlsx" `
  --cutoff-policy keep `
  --label "第1次" `
  --label "第2次"
```

`--cutoff-policy`:

- `keep`: 已发布提交序号保留旧截止；新提交序号首次发布使用当前 Excel 最新填写时间。
- `advance`: 把选中的提交序号推进到当前 Excel 最新填写时间。
- `manual`: 搭配 `--cutoff "第1次=2026-03-24 12:49:00"` 精确指定。

查看可用收集表：

```powershell
uv run python .\local\extract_homework.py --list-courses
```

查看某个 Excel 的提交序号和提交内容：

```powershell
uv run python .\local\extract_homework.py `
  --excel ".\config\算法分析与设计作业[B240401-03][大二下].xlsx" `
  --list-submission-labels
```

清理企业微信同步源附件默认关闭。需要清理时使用：

```powershell
uv run python .\local\extract_homework.py `
  --excel ".\config\算法分析与设计作业[B240401-03][大二下].xlsx" `
  --label "第1次" `
  --cleanup-source-attachments dry-run
```

确认 dry-run 报告后再改成 `apply`。

## Web 看板

公开数据结构：

- `webapp/public/courses.json`
- `webapp/public/course-manifest.json`
- `webapp/public/data/<课程>.index.json`
- `webapp/public/data/<课程>.<提交序号>.json`

`courses.json` 的课程项包含：

```ts
{
  课程: string
  数据文件: string
  主题: string
  对象: string
  周期?: string
  状态: 'active' | 'archived'
}
```

`data/<课程>.index.json` 使用：

```ts
{
  课程: string
  主题: string
  对象: string
  周期?: string
  状态: 'active' | 'archived'
  提交序号列表: Array<{
    提交序号: string
    数据文件: string
    提交内容列表: string[]
  }>
}
```

单个提交序号 JSON 使用 `提交序号` 作为主字段，并包含 `统计截止时间` 与 `补交状态`。

首页按 `周期` 分组。`archived` 课程仍可打开查看，但会显示“已归档”标识，不参与当前进行中语义。

本地预览：

```powershell
cd .\webapp
npm ci
npm run dev
```

构建：

```powershell
cd .\webapp
npm run lint
npm run build
```

## 常见问题

- 提示标题非法：确认标题是 `主题[对象]` 或 `主题[对象][周期]`，分隔符使用英文 `[` `]`。
- 提示 `提交内容` 非法：确认格式是 `内容名(.ext/.ext)`，括号和点号都用英文字符。
- 学生说已交但未计入：检查最新提交的上传文件后缀是否在该 `提交内容` 的括号契约内。
- 云端文件删了会不会丢：不会。只要本地 `archive_manifest.json` 里已有有效版本，后续统计会保留本地归档。
- 旧课程名 URL：不会重定向，旧标题访问会显示无效课程。

## 隐私

前端看板只展示学号和班级，不展示姓名。企业微信登录态、微盘同步和风控全部交给官方客户端；本项目只读取本地同步目录和导出的 Excel。
