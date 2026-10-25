# One-time install: Python venv + packages + frontend packages
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
if (-not (Test-Path ".venv")) { python -m venv .venv }
& "$root\.venv\Scripts\python.exe" -m pip install -r requirements.txt
Set-Location "$root\frontend"
npm install
