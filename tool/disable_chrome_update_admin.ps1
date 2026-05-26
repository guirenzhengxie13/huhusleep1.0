# 以管理员身份运行：禁用 Chrome/Google 自动更新服务与策略
$ErrorActionPreference = 'Continue'

$services = Get-Service | Where-Object {
    $_.Name -match 'gupdate|GoogleUpdater|GoogleChromeElevationService' -or
    $_.DisplayName -match 'Google.*Update|Google.*Updater'
}
foreach ($svc in $services) {
    Write-Host "Disabling service: $($svc.Name)"
    if ($svc.Status -ne 'Stopped') {
        Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
    }
    Set-Service -Name $svc.Name -StartupType Disabled -ErrorAction SilentlyContinue
}

$tasks = Get-ScheduledTask | Where-Object {
    $_.TaskName -match 'Google.*Update|GoogleUpdater' -or
    $_.TaskPath -match 'Google.*Update|GoogleUpdater'
}
foreach ($task in $tasks) {
    Write-Host "Disabling task: $($task.TaskPath)$($task.TaskName)"
    Disable-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -ErrorAction SilentlyContinue | Out-Null
}

$policyPath = 'HKLM:\SOFTWARE\Policies\Google\Update'
New-Item -Path $policyPath -Force | Out-Null
New-ItemProperty -Path $policyPath -Name AutoUpdateCheckPeriodMinutes -Value 0 -PropertyType DWord -Force | Out-Null
New-ItemProperty -Path $policyPath -Name UpdateDefault -Value 0 -PropertyType DWord -Force | Out-Null

Write-Host 'Done. Current Google update services:'
Get-Service | Where-Object {
    $_.Name -match 'gupdate|GoogleUpdater|GoogleChromeElevationService' -or
    $_.DisplayName -match 'Google.*Update|Google.*Updater'
} | Select-Object Name,Status,StartType | Format-Table -AutoSize
