# Weekday 09:21 job (Task Scheduler, New York time): ORB on its own Alpaca PAPER account
# (intraday/orb_alpaca.py; ALPACA_ORB_* paper keys; skipped until those are in .env). Same pick
# as the IBKR runner (IBKR scanner + bars, read-only client id 22), orders at Alpaca: stop-limit
# entry, a stop after the fill, the entry cancelled at 15:44 and the position closed
# market-on-close. Stays up until ~16:10 to book the fills.
# Kill switch: data/live/KILL blocks the entry; an open position is still closed.
# Log: data/logs/<date>-orb-alpaca.log
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs orb_alpaca
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed orb_alpaca }
exit $code
