param([int]$Port = 8765)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$runtime = Get-Command python -ErrorAction SilentlyContinue
$bundled = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($runtime) { $pythonExe = $runtime.Source }
elseif (Test-Path -LiteralPath $bundled) { $pythonExe = $bundled }
else { throw "需要 64 位 Python 3.12，请安装后重试。" }
if (!(Test-Path -LiteralPath 'data/ergou.sqlite')) {
    & $pythonExe -m ergou init --demo
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
$hasAdmin = & $pythonExe -c "import sqlite3; print(sqlite3.connect('data/ergou.sqlite').execute('select count(*) from users').fetchone()[0])"
if ($hasAdmin -eq '0') {
    & $pythonExe -m ergou user admin
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
}
& $pythonExe -m ergou serve --port $Port

