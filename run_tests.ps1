# Run API and ingest unit tests. Usage: .\run_tests.ps1
Set-Location $PSScriptRoot
python -m pytest api/tests ingest/tests -v
