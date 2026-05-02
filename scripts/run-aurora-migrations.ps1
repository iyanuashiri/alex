# Apply Alex Aurora DDL via RDS Data API (fixes "relation users does not exist" in Lambda).
# Requires: aws login (or SSO), uv, and Alex5Database deployed (or AURORA_* in .env).
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $env:DEFAULT_AWS_REGION) { $env:DEFAULT_AWS_REGION = "us-east-1" }
if (-not $env:AWS_REGION) { $env:AWS_REGION = $env:DEFAULT_AWS_REGION }

$db = Join-Path $RepoRoot "backend\database"
Set-Location $db
uv run python run_migrations.py
