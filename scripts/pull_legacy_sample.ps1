param(
    [string]$Server = "ubuntu@122.152.201.146",
    [string]$KeyPath = "$PSScriptRoot\..\.github_deploy_key",
    [string]$RemoteProject = "/home/ubuntu/pdd_kpi",
    [string]$Date = "2026-08-31",
    [string]$Destination = "$PSScriptRoot\..\v2\local_data\sample_$($Date.Replace('-', ''))"
)

$ErrorActionPreference = "Stop"
$archive = "/tmp/pdd_v2_legacy_sample_$($Date.Replace('-', ''))_$([guid]::NewGuid().ToString('N')).tgz"
$destinationPath = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force $destinationPath | Out-Null

try {
    $remoteCommand = "set -e; cd '$RemoteProject/data'; find processed -maxdepth 1 -type f -name 'orders_*_$Date.parquet' -print0 | tar --null -T - -czf '$archive' costs.json stores.json meta.json"
    & ssh -i $KeyPath -o StrictHostKeyChecking=no $Server $remoteCommand
    if ($LASTEXITCODE -ne 0) { throw "服务器打包失败" }
    & scp -i $KeyPath -o StrictHostKeyChecking=no "$Server`:$archive" "$destinationPath\legacy_sample.tgz"
    if ($LASTEXITCODE -ne 0) { throw "下载样本失败" }
    & tar -xzf "$destinationPath\legacy_sample.tgz" -C $destinationPath
    if ($LASTEXITCODE -ne 0) { throw "本地解压样本失败" }
    Remove-Item -LiteralPath "$destinationPath\legacy_sample.tgz" -Force
    & python "$PSScriptRoot\..\v2\legacy_profile.py" --source $destinationPath --output "$destinationPath\migration_profile.json"
    if ($LASTEXITCODE -ne 0) { throw "本地迁移画像生成失败：请确认本机 Python 已安装 pyarrow 或 fastparquet" }
    Write-Host "旧版样本已保存到 $destinationPath"
    Write-Host "迁移报告：$destinationPath\migration_profile.json"
}
finally {
    & ssh -i $KeyPath -o StrictHostKeyChecking=no $Server "rm -f '$archive'" 2>$null
}
