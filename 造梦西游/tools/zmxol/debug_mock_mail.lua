-- 桌面 Lua 5.4 追加独立调试邮件；保留正式已领取收据，原客户端无已确认的 Lua API。
local kind = arg[1]
if kind ~= "pet" and kind ~= "pill" and kind ~= "bagua" then
  io.stderr:write("Usage: lua debug_mock_mail.lua pet|pill|bagua [serial] [python] [--dry-run]\n")
  os.exit(2)
end
local function quote(value)
  return "'" .. value:gsub("'", "'\\''") .. "'"
end
local directory = arg[0]:match("^(.*)/") or "."
local python = arg[3] or "python3"
local command = quote(python) .. " " .. quote(directory .. "/debug_mock_mail.py")
  .. " --kind " .. quote(kind) .. " --serial " .. quote(arg[2] or "emulator-5576")
if arg[4] then
  if arg[4] ~= "--dry-run" then os.exit(2) end
  command = command .. " --dry-run"
end
local ok, _, status = os.execute(command)
os.exit(ok and 0 or (status or 1))
