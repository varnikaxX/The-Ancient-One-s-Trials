$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$root\.venv\Scripts\Activate.ps1"
Set-Location "$root\backend"
$env:PYTHONPATH = ".."
uvicorn app.main:app --reload --port 8000
