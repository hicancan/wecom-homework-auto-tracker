param(
    [string]$ConfigPath = "",
    [string]$CoursesDir = "",
    [string]$PythonExe = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Resolve-ConfigPath {
    param(
        [string]$RepoRoot,
        [string]$InputConfigPath
    )
    if ([string]::IsNullOrWhiteSpace($InputConfigPath)) {
        return (Join-Path $RepoRoot "config\local.config.json")
    }
    if ([System.IO.Path]::IsPathRooted($InputConfigPath)) {
        return $InputConfigPath
    }
    return (Join-Path $RepoRoot $InputConfigPath)
}

function Resolve-PathFromRepo {
    param(
        [string]$RepoRoot,
        [string]$Candidate,
        [string]$DefaultPath
    )
    $raw = if ([string]::IsNullOrWhiteSpace($Candidate)) { $DefaultPath } else { $Candidate }
    if ([string]::IsNullOrWhiteSpace($raw)) {
        throw "路径为空，无法继续。"
    }
    if ([System.IO.Path]::IsPathRooted($raw)) {
        return $raw
    }
    return (Join-Path $RepoRoot $raw)
}

function Resolve-PythonExe {
    param(
        [string]$RepoRoot,
        [string]$InputPythonExe
    )
    if (-not [string]::IsNullOrWhiteSpace($InputPythonExe)) {
        $candidate = $InputPythonExe
        if (-not [System.IO.Path]::IsPathRooted($candidate)) {
            $candidate = Join-Path $RepoRoot $candidate
        }
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
        throw "指定的 Python 可执行文件不存在: $candidate"
    }

    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        return (Resolve-Path $venvPython).Path
    }

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }

    throw "未找到 Python。请先创建 .venv 或通过 -PythonExe 显式指定。"
}

function Get-CourseFiles {
    param([string]$ResolvedCoursesDir)
    if (-not (Test-Path $ResolvedCoursesDir)) {
        throw "课程目录不存在: $ResolvedCoursesDir"
    }
    $files = Get-ChildItem -Path $ResolvedCoursesDir -File |
        Where-Object {
            ($_.Extension -in @(".xlsx", ".xls")) -and (-not $_.Name.StartsWith('~$'))
        } |
        Sort-Object Name

    if ($files.Count -eq 0) {
        throw "课程目录下没有可用 Excel: $ResolvedCoursesDir"
    }
    return $files
}

function Parse-IndexSelection {
    param(
        [string]$InputText,
        [int]$MaxIndex
    )
    if ([string]::IsNullOrWhiteSpace($InputText)) {
        throw "未输入课程编号。"
    }
    # Normalize common full-width punctuation for easier input, e.g. "1，2".
    $text = $InputText.Trim().TrimStart([char]0xFEFF).ToLowerInvariant().Replace("，", ",").Replace("、", ",")
    if ($text -eq "all") {
        return 1..$MaxIndex
    }

    $picked = New-Object System.Collections.Generic.HashSet[int]
    $parts = $text.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
    foreach ($part in $parts) {
        if ($part -match "^(\d+)-(\d+)$") {
            $start = [int]$Matches[1]
            $end = [int]$Matches[2]
            if ($start -gt $end) {
                throw "区间 '$part' 非法（起点大于终点）。"
            }
            foreach ($i in $start..$end) {
                if ($i -lt 1 -or $i -gt $MaxIndex) {
                    throw "编号 '$i' 超出范围 1-$MaxIndex。"
                }
                [void]$picked.Add($i)
            }
            continue
        }
        if ($part -match "^\d+$") {
            $i = [int]$part
            if ($i -lt 1 -or $i -gt $MaxIndex) {
                throw "编号 '$i' 超出范围 1-$MaxIndex。"
            }
            [void]$picked.Add($i)
            continue
        }
        throw "无法解析课程选择片段: '$part'"
    }

    return @($picked) | Sort-Object
}

function Read-PositiveInt {
    param([string]$Prompt)
    while ($true) {
        $raw = Read-Host $Prompt
        if ($raw -match "^\d+$") {
            $n = [int]$raw
            if ($n -gt 0) {
                return $n
            }
        }
        Write-Host "请输入正整数。" -ForegroundColor Yellow
    }
}

function Read-YesNo {
    param(
        [string]$Prompt,
        [string]$Default = "N"
    )
    $defaultUpper = $Default.Trim().ToUpperInvariant()
    if ($defaultUpper -ne "Y" -and $defaultUpper -ne "N") {
        $defaultUpper = "N"
    }

    while ($true) {
        $suffix = if ($defaultUpper -eq "Y") { "[Y/n]" } else { "[y/N]" }
        $raw = Read-Host "$Prompt $suffix"
        if ([string]::IsNullOrWhiteSpace($raw)) {
            return ($defaultUpper -eq "Y")
        }
        $v = $raw.Trim().ToLowerInvariant()
        if ($v -in @("y", "yes")) { return $true }
        if ($v -in @("n", "no")) { return $false }
        Write-Host "请输入 y 或 n。" -ForegroundColor Yellow
    }
}

$repoRoot = Resolve-RepoRoot
$configPathResolved = Resolve-ConfigPath -RepoRoot $repoRoot -InputConfigPath $ConfigPath
$extractScript = Join-Path $repoRoot "local\extract_homework.py"
if (-not (Test-Path $extractScript)) {
    throw "找不到提取脚本: $extractScript"
}

$configObj = $null
if (Test-Path $configPathResolved) {
    $configObj = Get-Content -Raw $configPathResolved | ConvertFrom-Json
}

$configCoursesDir = ""
if ($null -ne $configObj -and $null -ne $configObj.courses_dir) {
    $configCoursesDir = [string]$configObj.courses_dir
}

$resolvedCoursesDir = Resolve-PathFromRepo `
    -RepoRoot $repoRoot `
    -Candidate $CoursesDir `
    -DefaultPath $(if ([string]::IsNullOrWhiteSpace($configCoursesDir)) { "config" } else { $configCoursesDir })
$resolvedCoursesDir = (Resolve-Path $resolvedCoursesDir).Path

$pythonExeResolved = Resolve-PythonExe -RepoRoot $repoRoot -InputPythonExe $PythonExe
$courseFiles = Get-CourseFiles -ResolvedCoursesDir $resolvedCoursesDir

Write-Host ""
Write-Host "可选课程列表（来源: $resolvedCoursesDir）" -ForegroundColor Cyan
for ($i = 0; $i -lt $courseFiles.Count; $i++) {
    $idx = $i + 1
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($courseFiles[$i].Name)
    Write-Host ("[{0}] {1}" -f $idx, $baseName)
}
Write-Host ""

$selectedIndexes = $null
while ($true) {
    $raw = Read-Host "请选择课程编号（如 1,3-4 或 all）"
    try {
        $selectedIndexes = Parse-IndexSelection -InputText $raw -MaxIndex $courseFiles.Count
        break
    }
    catch {
        Write-Host $_.Exception.Message -ForegroundColor Yellow
    }
}

$plan = @()
foreach ($idx in $selectedIndexes) {
    $file = $courseFiles[$idx - 1]
    $courseName = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
    Write-Host ""
    Write-Host "配置区间: $courseName" -ForegroundColor Cyan
    $from = Read-PositiveInt -Prompt "  --from"
    $to = Read-PositiveInt -Prompt "  --to"
    while ($from -gt $to) {
        Write-Host "  from 不能大于 to，请重新输入。" -ForegroundColor Yellow
        $from = Read-PositiveInt -Prompt "  --from"
        $to = Read-PositiveInt -Prompt "  --to"
    }

    $plan += [PSCustomObject]@{
        Course = $courseName
        Excel  = $file.FullName
        From   = $from
        To     = $to
    }
}

Write-Host ""
Write-Host "执行预览：" -ForegroundColor Cyan
$plan | Format-Table -AutoSize
Write-Host ""

if (-not (Read-YesNo -Prompt "确认执行以上计划？" -Default "N")) {
    Write-Host "已取消执行。" -ForegroundColor Yellow
    exit 0
}

$failed = @()
foreach ($item in $plan) {
    Write-Host ""
    Write-Host ("开始处理: {0} --from {1} --to {2}" -f $item.Course, $item.From, $item.To) -ForegroundColor Cyan
    $args = @(
        $extractScript,
        "--excel", $item.Excel,
        "--from", [string]$item.From,
        "--to", [string]$item.To
    )
    & $pythonExeResolved @args
    if ($LASTEXITCODE -ne 0) {
        $failed += $item
        Write-Host ("处理失败: {0}" -f $item.Course) -ForegroundColor Red
    }
    else {
        Write-Host ("处理完成: {0}" -f $item.Course) -ForegroundColor Green
    }
}

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host "以下课程处理失败：" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host ("- {0}" -f $_.Course) -ForegroundColor Red }
    exit 1
}

Write-Host "全部课程处理完成。" -ForegroundColor Green
