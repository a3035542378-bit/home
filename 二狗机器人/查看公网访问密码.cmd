@echo off
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; $file=Join-Path $env:LOCALAPPDATA 'Ergou\CloudAccess\203.0.113.10.xml'; $account=Import-Clixml -LiteralPath $file; Write-Host 'https://203.0.113.10/ergou/'; Write-Host ('HTTPS username: ' + $account.UserName); Write-Host ('HTTPS password: ' + $account.GetNetworkCredential().Password)"
pause
