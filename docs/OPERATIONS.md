# WeCom Collection Tracker Operations

更新日期：2026-06-09

## 当前模型

唯一收集表契约：

```text
主题[对象][周期] + 提交序号 + 提交内容(.ext/.ext) + 请上传对应文件
```

唯一业务键：

```text
学号 + 提交序号 + 提交内容
```

`collection_id` 是稳定机器 ID，中文标题只用于展示和匹配企业微信导出表。标题可调整，`collection_id` 不应调整。

## 发布口径

- 默认是截止模式：只统计截止时间内有效文件，ZIP 不包含补交文件。
- 只有显式启用补交窗口时，才统计窗口内有效补交，ZIP 同步包含这些补交文件。
- 后缀格式无效的文件保留在本地版本归档用于审计，但不计入提交率、不进入 ZIP。
- 前端只展示四种业务状态：绿色已提交、蓝色补交、红色未达标、黄色后缀格式无效。

## 当前固定补交窗口

算法作业第1次至第6次使用同一补交窗口：

```text
2026-06-09 09:52:00 至 2026-06-09 22:40:00
```

执行命令：

```powershell
uv run python .\local\extract_homework.py `
  --config .\config\local.config.json `
  --collection-id algorithm-design-homework-b240401-03-sophomore-spring `
  --label 第1次 `
  --label 第2次 `
  --label 第3次 `
  --label 第4次 `
  --label 第5次 `
  --label 第6次 `
  --cutoff-policy keep `
  --publish-mode makeup-window `
  --makeup-window-start "2026-06-09 09:52:00" `
  --makeup-window-end "2026-06-09 22:40:00" `
  --skip-unknown
```

## 本地归档结构

```text
out/collections/<collection_id>/
  archive_manifest.json
  files/
    _versions/<entry_token>/<version_token>/<学号姓名.ext>
    current/<提交序号>/<提交内容>/<班级>/<学号姓名.ext>
  zip/<提交序号>.zip
  stats/<提交序号>.json
  collection_summary.json
```

`archive_manifest.json` 与 `_versions/` 是权威归档。`current/`、`zip/`、`stats/` 是可重建发布视图。

## 常用命令

```powershell
# 交互模式
uv run python .\scripts\run_extract_interactive.py --config .\config\local.config.json

# 列出收集表
uv run python .\local\extract_homework.py --config .\config\local.config.json --list-collections

# 列出提交序号
uv run python .\local\extract_homework.py `
  --config .\config\local.config.json `
  --collection-id algorithm-design-homework-b240401-03-sophomore-spring `
  --list-submission-labels

# Python 验证
uv run python -m compileall -q .\local .\scripts
uv run pytest

# 前端验证
cd webapp
npm run lint
npm run build
```

## 运维约束

- `config/local.config.json`、真实学生名单、真实补修/重修名单、企业微信 Excel 均不进入 Git。
- 新 Excel 必须有 `提交序号`、`提交内容`、`请上传对应文件`、`填写时间`。
- `提交内容` 不允许为空，必须写成 `内容名(.ext/.ext)`。
- 新增补修/重修学生必须进入本地 ignored 名单，否则默认 fail-fast。
- 企业微信同步目录清理后，已进入本地归档的版本不受影响；未进入归档的源文件无法从系统内恢复。
