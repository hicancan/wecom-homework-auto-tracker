# WeCom Collection Tracker

企业微信收集表的本地增量归档与公开追踪看板。

## 数据模型

唯一表单契约：

```text
主题[对象][周期] + 提交序号 + 提交内容(.ext/.ext) + 请上传对应文件
```

示例标题：

```text
人工智能导论及其Python应用实践实验[B240402][大二下]
算法分析与设计作业[B240401-03][大二下]
算法分析与设计实验[B240401-03][大二下]
```

唯一业务键：

```text
学生 + 提交序号 + 提交内容
```

每个收集表必须在本地配置里绑定稳定 ASCII `collection_id`。标题可以改，`collection_id` 不应该改。

## 本地配置

复制模板：

```powershell
Copy-Item .\config\config.template.json .\config\config.json
```

核心字段：

```json
{
  "collections_dir": "config",
  "attachments_root": "C:/Users/yourname/Documents/WXWork/your-id/WeDrive/your-org/我的文件",
  "students": "config/students.json",
  "other_students": "config/other_students.json",
  "out_root": "out",
  "web_data_root": "webapp/public/data",
  "collection_index": "webapp/public/collections.json",
  "collections": {
    "example-collection-b240401-sophomore-spring": {
      "title": "示例主题[B240401][大二下]",
      "excel": "config/示例主题[B240401][大二下].xlsx",
      "status": "active",
      "classes": ["B240401"]
    }
  }
}
```

`config/*.json` 和 Excel 默认不进入 Git。真实补修/重修名单放 `config/other_students.json`，仓库只保留 `config/other_students.template.json`。

## 收集命令

列出可提取的收集表：

```powershell
uv run python .\local\extract_homework.py --config .\config\config.json --list-collections
```

列出提交序号：

```powershell
uv run python .\local\extract_homework.py `
  --config .\config\config.json `
  --collection-id example-collection-b240401-sophomore-spring `
  --list-submission-labels
```

增量收集指定提交序号：

```powershell
uv run python .\local\extract_homework.py `
  --config .\config\config.json `
  --collection-id example-collection-b240401-sophomore-spring `
  --label 第1次 `
  --cutoff-policy keep `
  --publish-mode cutoff
```

截止策略：

- `keep`: 已发布提交序号保留旧截止；新提交序号首次发布使用当前 Excel 最新填写时间。
- `advance`: 推进到当前 Excel 最新填写时间。
- `manual`: 使用 `--cutoff "第1次=YYYY-MM-DD HH:MM:SS"`。

发布模式：

- `cutoff`: 默认模式，只发布统计截止时间内的有效提交；页面显示“不允许补交”，ZIP 不含补交。
- `makeup-window`: 补交窗口模式，发布截止内有效提交 + 补交窗口内有效提交；必须提供 `--makeup-window-end "YYYY-MM-DD HH:MM:SS"`。

补交窗口示例：

```powershell
uv run python .\local\extract_homework.py `
  --config .\config\config.json `
  --collection-id example-collection-b240401-sophomore-spring `
  --label 第1次 `
  --cutoff-policy keep `
  --publish-mode makeup-window `
  --makeup-window-end "2026-06-09 22:40:00"
```

交互入口：

```powershell
uv run python .\scripts\run_extract_interactive.py --config .\config\config.json
```

## 本地归档

归档根目录：

```text
out/collections/<collection_id>/
  archive_manifest.json
  files/
    _versions/
    current/<提交序号>/<提交内容>/<班级>/<学号姓名.ext>
  zip/<提交序号>.zip
  stats/<提交序号>.json
  collection_summary.json
```

`archive_manifest.json` 是本地权威基线。企业微信同步目录删除源文件时，只要本地归档已有有效版本，就不会回退为未提交。

后缀格式无效的版本会保留在归档中用于审计，但不计入有效提交，不进入 zip。

## 公开数据

公开入口：

```text
webapp/public/collections.json
webapp/public/data/<collection_id>/index.json
webapp/public/data/<collection_id>/seq-001.json
```

前端路由：

```text
/#/collection/<collection_id>?seq=seq-001
```

旧标题路由和旧参数不重定向，直接显示无效。

## 状态口径

- 绿色：截止时间内有效提交。
- 蓝色：补交窗口内有效补交，仅在补交窗口模式显示。
- 红色：本次发布口径内仍未提交。
- 黄色：本次发布口径内最新提交后缀格式无效。

默认截止模式的提交率和 zip 只按截止时间内有效提交计算。补交窗口模式的提交率和 zip 按“截止内有效提交 + 补交窗口内有效提交”计算。

## 验证

```powershell
$files = @(Get-ChildItem -Path .\local, .\scripts -Filter *.py | ForEach-Object { $_.FullName })
uv run python -m py_compile @files
uv run pytest
cd webapp
npm run lint
npm run test
npm run build
```

发布后检查：

```text
https://homework.hicancan.top/
https://homework.hicancan.top/#/collection/<collection_id>?seq=seq-001
```
