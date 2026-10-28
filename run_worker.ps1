$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$root\.venv\Scripts\Activate.ps1"
Set-Location "$root\backend"
$env:PYTHONPATH = ".."
celery -A workers.celery_app worker --loglevel=info --pool=solo
