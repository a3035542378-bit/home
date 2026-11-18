[CmdletBinding()]
param([string]$Database, [string]$NativeExe, [switch]$NoBrowser, [switch]$ReviewNotice, [switch]$ReviewMembers, [switch]$ReviewVoice)

$ErrorActionPreference = 'Stop'
$rootDir = Split-Path -Parent $PSScriptRoot
$expectedHash = 'D63A9A7C1484D814C6E53B9A0F47353FCAD0F7575107666CA3A9B072E28A59D5'

function Find-LiveDatabase([string]$Explicit) {
    if ($Explicit) { return (Resolve-Path -LiteralPath $Explicit).Path }
    $default = Join-Path $env:LOCALAPPDATA 'Ergou\Robot\ergou.sqlite'
    if (Test-Path -LiteralPath $default -PathType Leaf) { return $default }
    $packages = Join-Path $env:LOCALAPPDATA 'Packages'
    $candidates = @(if (Test-Path -LiteralPath $packages) {
        foreach ($dir in Get-ChildItem -LiteralPath $packages -Directory -Filter 'OpenAI.Codex_*') {
            $path = Join-Path $dir.FullName 'LocalCache\Local\Ergou\Robot\ergou.sqlite'
            if (Test-Path -LiteralPath $path -PathType Leaf) { $path }
        }
    })
    if ($candidates.Count -ne 1) { throw '无法唯一定位正式数据库。请用 -Database 指定已绑定微信的二狗数据库。' }
    return $candidates[0]
}

function Get-LivePatterns([string]$Db, [string]$Profile) {
    # A packaged shell sees the same files under unredirected LocalAppData paths.
    $dbNames = @($Db)
    $profileNames = @($Profile)
    $ordinaryDb = Join-Path $env:LOCALAPPDATA 'Ergou\Robot\ergou.sqlite'
    $packageRoot = Join-Path $env:LOCALAPPDATA 'Packages\OpenAI.Codex_*\LocalCache\Local\Ergou\Robot\ergou.sqlite'
    if ($Db -like $packageRoot -and !(Test-Path -LiteralPath $ordinaryDb)) {
        $dbNames += $ordinaryDb
        $profileNames += Join-Path $env:LOCALAPPDATA 'Ergou\WechatListener'
    }
    $dbRx = '(?:"' + (($dbNames | ForEach-Object {[Regex]::Escape($_)}) -join '"|"') + '"|' + (($dbNames | ForEach-Object {[Regex]::Escape($_)}) -join '|') + ')'
    $profileRx = '(?:"' + (($profileNames | ForEach-Object {[Regex]::Escape($_)}) -join '"|"') + '"|' + (($profileNames | ForEach-Object {[Regex]::Escape($_)}) -join '|') + ')'
    $exeRx = '^(?:"[^"]+"|\S+)\s+-m\s+'
    $agent = $exeRx+'ergou\.agent_wechat\s+--db\s+'+$dbRx+'\s+--private-dir\s+'+$profileRx+'\s+'
    return @{
        core=$exeRx+'ergou\s+--db\s+'+$dbRx+'\s+serve\s+--port\s+8766\s*$'
        listener=$agent+'listen\s*$'
        replies=$agent+'(?:resume-replies|replies\s+--group-name\s+(?:"[^"]+"|\S+))\s*$'
    }
}

function Find-Worker([string]$Pattern) {
    $found = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
        $_.ExecutablePath -eq $pythonExe -and $_.CommandLine -match $Pattern
    })
    if ($found.Count -gt 1) { throw '检测到多个同一角色的后台进程，请先核对现有实例。' }
    if ($found.Count) { return [int]$found[0].ProcessId }
}

function Get-PortOwner([int]$Port) {
    $endpoints = @(Get-NetTCPConnection -State Listen | Where-Object {
        $_.LocalPort -eq $Port -and $_.LocalAddress -in @('127.0.0.1','0.0.0.0','::')
    })
    if (!$endpoints.Count) { return }
    if ($endpoints.Count -ne 1 -or $endpoints[0].LocalAddress -ne '127.0.0.1') {
        throw "端口 $Port 未独占绑定到本机回环地址。"
    }
    return [int]$endpoints[0].OwningProcess
}

function Start-Worker([string]$Name,[string]$Arguments) {
    $log = Join-Path (Split-Path -Parent $dbPath) ("launch-"+$Name+"-"+[DateTime]::Now.ToString('yyyyMMdd-HHmmssfff')+".log")
    $new = Start-Process -FilePath $pythonExe -WorkingDirectory $rootDir -ArgumentList $Arguments `
        -WindowStyle Hidden -RedirectStandardError $log -PassThru
    Start-Sleep -Milliseconds 450
    if ($new.HasExited) { throw "启动 $Name 失败，日志位于 $log" }
    return $new.Id
}

function Wait-Port([int]$Port) {
    $limit = [DateTime]::UtcNow.AddSeconds(15)
    do {
        $ownerId = Get-PortOwner $Port
        if ($ownerId) { return $ownerId }
        Start-Sleep -Milliseconds 300
    } while ([DateTime]::UtcNow -lt $limit)
    throw "等待二狗服务端口 $Port 超时。"
}

function Open-LiveDesk {
    $dbPath = Find-LiveDatabase $Database
    $dataRoot = Split-Path -Parent (Split-Path -Parent $dbPath)
    $profile = Join-Path $dataRoot 'WechatListener'
    $pythonExe = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (!(Test-Path -LiteralPath $pythonExe)) { $pythonExe = (Get-Command python.exe -CommandType Application | Select-Object -First 1).Source }
    $env:PYTHONUTF8='1'
    if ($ReviewNotice) {
        $number = Read-Host '请输入运营后台「定时通知」中要确认的通知编号'
        if ($number -notmatch '^[1-9][0-9]{0,17}$') { throw '请输入有效通知编号。' }
        & $pythonExe -m ergou --db $dbPath confirm-notice $number
        if ($LASTEXITCODE) { throw '单次通知确认失败。' }
        return
    }
    if ($ReviewMembers) {
        & $pythonExe -m ergou --db $dbPath confirm-member-notice
        if ($LASTEXITCODE) { throw '成员通知确认失败。' }
    }
    if ($ReviewVoice) {
        & $pythonExe -m ergou --db $dbPath confirm-voice
        if ($LASTEXITCODE) { throw '语音授权确认失败。' }
    }
    $patterns = Get-LivePatterns $dbPath $profile
    $backend = Find-Worker $patterns.core
    $ownerId = Get-PortOwner 8766
    if ($ownerId -and $ownerId -ne $backend) { throw '8766 端口由其他程序使用，请核对端口与正式数据库。' }
    & $pythonExe -m ergou --db $dbPath first-operator
    if ($LASTEXITCODE) { throw '后台账号初始化失败。' }
    if (!$backend) { $backend = Start-Worker 'core' ('-m ergou --db "'+$dbPath+'" serve --port 8766') }
    if ((Wait-Port 8766) -ne $backend) { throw '后台监听进程与正式数据库实例不符。' }
    if (!$NoBrowser) { Start-Process 'http://127.0.0.1:8766/' }
    $planText = & $pythonExe -m ergou.agent_wechat --db $dbPath --private-dir $profile recovery-plan
    if ($LASTEXITCODE) { throw '无法读取当前绑定。' }
    $plan = $planText | ConvertFrom-Json
    if (!$plan.listen) { Write-Host '后台已就绪。当前没有可恢复的微信绑定。'; return }
    foreach ($credential in @('ergou-read-token','ergou-node-secret')) {
        if (!(Test-Path -LiteralPath (Join-Path $profile $credential) -PathType Leaf)) { throw "缺少监听凭据 $credential。后台可正常使用。" }
    }
    $nativeOwner = Get-PortOwner 6174
    if (!$nativeOwner) {
        if (!$NativeExe) { $NativeExe = Join-Path $rootDir 'build\agent-wechat-v2.7.1\wx.exe' }
        if (!(Test-Path -LiteralPath $NativeExe -PathType Leaf)) { throw '未找到已固定版本的微信插件 wx.exe。请用 -NativeExe 指定其位置。' }
        $helper = Join-Path $PSScriptRoot 'agent-wechat-start.ps1'
        $shell = (Get-Process -Id $PID).Path
        $nativeArgs = '-NoProfile -ExecutionPolicy RemoteSigned -File "'+$helper+'" -Wx "'+(Resolve-Path -LiteralPath $NativeExe).Path+'" -DataDir "'+$profile+'"'
        Start-Process -FilePath $shell -ArgumentList $nativeArgs -WorkingDirectory $rootDir -WindowStyle Hidden
        $nativeOwner = Wait-Port 6174
    }
    $native = Get-CimInstance Win32_Process -Filter "ProcessId=$nativeOwner"
    if (!$native.ExecutablePath -or (Get-FileHash -LiteralPath $native.ExecutablePath -Algorithm SHA256).Hash -ne $expectedHash) {
        throw '6174 端口未能核实为已固定版本的微信插件。'
    }
    $argsPrefix = '-m ergou.agent_wechat --db "'+$dbPath+'" --private-dir "'+$profile+'" '
    & $pythonExe -m ergou.agent_wechat --db $dbPath --private-dir $profile prepare-voice-media --wx $native.ExecutablePath
    if ($LASTEXITCODE) { throw '本群语音媒体权限准备失败。' }
    if (!(Find-Worker $patterns.listener)) { $null=Start-Worker 'listener' ($argsPrefix+'listen') }
    if ($plan.replies -and !(Find-Worker $patterns.replies)) {
        if (!(Test-Path -LiteralPath (Join-Path $profile 'ergou-send-token') -PathType Leaf)) { throw '已恢复监听，回复进程缺少本机发送凭据。' }
        $null=Start-Worker 'replies' ($argsPrefix+'resume-replies')
    }
    Write-Host '已核对正式后台和已授权的微信服务。'
}

if ($MyInvocation.InvocationName -ne '.') {
    Set-Location -LiteralPath $rootDir
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $mutex = New-Object System.Threading.Mutex($false,("Local\ErgouLiveLauncher-"+$sid))
    $locked=$false
    try {
        try { $locked=$mutex.WaitOne(30000) } catch [System.Threading.AbandonedMutexException] { $locked=$true }
        if (!$locked) { throw '已有启动窗口正在处理当前实例。' }
        Open-LiveDesk
    } finally {
        if ($locked) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}
