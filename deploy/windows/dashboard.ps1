# Dashboard at logon (read-only). Binds HT_DASHBOARD_HOST from .env (the mini's Tailscale IP),
# default 127.0.0.1. Never 0.0.0.0 on a public network: the dashboard has no login.
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.dashboard
