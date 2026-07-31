# 学习检查自动化 - Windows 任务计划程序安装脚本
# 右键 → 使用 PowerShell 运行，或管理员终端执行：
#   powershell -ExecutionPolicy Bypass -File schedule_setup.ps1

$ErrorActionPreference = "Stop"
$TaskName = "LearningCheck-Auto"

# 项目路径
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunBat = Join-Path $ProjectDir "run.bat"

Write-Host "========================================"  -ForegroundColor Cyan
Write-Host "  学习检查自动化 - 定时任务安装"        -ForegroundColor Cyan
Write-Host "========================================"  -ForegroundColor Cyan
Write-Host ""
Write-Host "项目目录 : $ProjectDir"
Write-Host "启动脚本 : $RunBat"
Write-Host ""

# 检查管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")
if (-not $isAdmin) {
    Write-Host "需要管理员权限！请右键 → 以管理员身份运行 PowerShell" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# 删除旧任务（如果存在）
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "检测到已有任务，正在更新..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# 创建触发条件：每日 08:00
$Trigger = New-ScheduledTaskTrigger -Daily -At "08:00"

# 创建动作：运行 run.bat
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$RunBat`"" -WorkingDirectory $ProjectDir

# 配置任务设置
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

# 创建任务（以当前用户身份运行）
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask `
    -TaskName $TaskName `
    -Trigger $Trigger `
    -Action $Action `
    -Settings $Settings `
    -Principal $Principal `
    -Description "学习检查自动化：每天 08:00 自动检查门店员工华为零售助手学习完成情况" `
    -Force

Write-Host ""
Write-Host "========================================"   -ForegroundColor Green
Write-Host "  定时任务安装成功！"                       -ForegroundColor Green
Write-Host "========================================"   -ForegroundColor Green
Write-Host ""
Write-Host "任务名称 : $TaskName"
Write-Host "执行时间 : 每天 08:00"
Write-Host "执行脚本 : $RunBat"
Write-Host ""
Write-Host "管理方式：" -ForegroundColor Cyan
Write-Host "  · 查看: taskschd.msc → 搜索 '$TaskName'"
Write-Host "  · 手动运行: schtasks /Run /TN '$TaskName'"
Write-Host "  · 删除任务: schtasks /Delete /TN '$TaskName' /F"
Write-Host "  · 修改时间: taskschd.msc → 右键任务 → 属性 → 触发器"
Write-Host ""

# 立即运行一次测试
$confirm = Read-Host "是否立即运行一次测试？(y/n)"
if ($confirm -eq "y" -or $confirm -eq "Y") {
    Write-Host "正在启动任务..." -ForegroundColor Cyan
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "任务已启动，请检查输出。" -ForegroundColor Green
}

Read-Host "按回车退出"
