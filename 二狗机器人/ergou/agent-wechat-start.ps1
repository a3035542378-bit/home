param(
    [Parameter(Mandatory=$true)][string]$Wx,
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'Ergou\WechatListener'),
    [switch]$Isolated
)
$ErrorActionPreference = 'Stop'
if (-not $Isolated) {
    $shell = (Get-Process -Id $PID).Path
    & $shell -NoProfile -File $PSCommandPath -Wx $Wx -DataDir $DataDir -Isolated
    exit $LASTEXITCODE
}
$exe = (Resolve-Path -LiteralPath $Wx).Path
if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash -ne 'D63A9A7C1484D814C6E53B9A0F47353FCAD0F7575107666CA3A9B072E28A59D5') {
    throw 'Expected upstream Agent WeChat v2.7.1 win32-x64.'
}
# An elevated Administrator token can name the Administrators group as its
# default owner. SQLite creates sidecar files itself. Have this short-lived
# launcher and its daemon create them with the signed-in user as the owner.
# The daemon still applies and checks its own private DACL on every file.
$access = [Security.Principal.TokenAccessLevels]'Query,AdjustDefault'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent($access)
if ($identity.Owner -ne $identity.User) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class ErgouFileOwner {
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool SetTokenInformation(SafeAccessTokenHandle token, int infoClass,
                                           ref IntPtr value, int size);
    public static void UseCurrentUser(SafeAccessTokenHandle token, byte[] userSid) {
        var bytes = GCHandle.Alloc(userSid, GCHandleType.Pinned);
        try {
            var sid = bytes.AddrOfPinnedObject();
            if (!SetTokenInformation(token, 4, ref sid, IntPtr.Size))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        } finally { bytes.Free(); }
    }
}
'@
    $sid = New-Object byte[] $identity.User.BinaryLength
    $identity.User.GetBinaryForm($sid, 0)
    [ErgouFileOwner]::UseCurrentUser($identity.AccessToken, $sid)
}
$identity.Dispose()
& $exe --data-dir $DataDir --listen 127.0.0.1:6174 --server http://127.0.0.1:6174 daemon start
exit $LASTEXITCODE
