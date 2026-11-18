param(
    [string]$Target = 'ubuntu@203.0.113.10',
    [string]$IdentityFile = (Join-Path $env:USERPROFILE '.ssh\id_ed25519'),
    [int]$LocalPort = 8767,
    [switch]$TunnelOnly
)
$ErrorActionPreference = 'Stop'
$forward = "127.0.0.1:${LocalPort}:127.0.0.1:8766"
$listener = Get-NetTCPConnection -State Listen -LocalPort $LocalPort -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($listener.LocalAddress -ne '127.0.0.1' -or $owner.Name -ne 'ssh.exe' -or
        !$owner.CommandLine.Contains($forward) -or !$owner.CommandLine.Contains($Target)) {
        throw "本机端口 $LocalPort 已被其他程序占用。"
    }
} else {
    $arguments = @('-N','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=3',
        '-o','ConnectTimeout=8','-L',$forward)
    if (Test-Path -LiteralPath $IdentityFile) {
        $arguments += @('-o','IdentitiesOnly=yes','-i',('"' + $IdentityFile + '"'))
    }
    $process = Start-Process ssh.exe -ArgumentList ($arguments + $Target) -WindowStyle Hidden -PassThru
}
$url = "http://127.0.0.1:$LocalPort/"
for ($i = 0; $i -lt 25; $i++) {
    if ($process -and $process.HasExited) { throw '免密 SSH 连接失败，请检查密钥和服务器状态。' }
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $url
        if ($response.StatusCode -eq 200 -and $response.Content.Contains('id="wechatLogin"')) {
            if (!$TunnelOnly) { Start-Process $url }
            Write-Output $url
            exit 0
        }
    } catch { }
    Start-Sleep -Milliseconds 350
}
throw '隧道未能连通二狗后台，请核对云端服务状态。'
