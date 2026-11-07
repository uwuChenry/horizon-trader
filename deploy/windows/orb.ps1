# Weekday 09:21 job (Task Scheduler, New York time): ORB on the IBKR PAPER account
# (intraday/orb_live.py). Waits for 09:35:05, takes IBKR's "5min volume vs average" scanner,
# ranks by exact relative volume, then places one bracket: stop-limit entry at the opening-range
# break (GTD 15:44) + 1-ATR stop + market-on-close, so IBKR manages the exit. Usually exits at
# ~09:36; stays up to 15:45 only if IBKR rejects the MOC child. Needs IB Gateway logged in and
# the morning job's Massive files (yesterday). Fills are booked by the evening job (orb sync).
# Kill switch: data/live/KILL. Steps live in horizon_trader/ops/jobs.py.
# Log: data/logs/<date>-orb.log
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs orb
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed orb }
exit $code
