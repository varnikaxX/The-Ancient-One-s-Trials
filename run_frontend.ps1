$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$root\frontend"
npm run dev
