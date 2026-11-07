# Weekday morning job (Task Scheduler, 08:00 New York time; this PC's clock must be Eastern).
# Steps live in horizon_trader/ops/jobs.py:
# 1. Download yesterday's Massive day file.
# 2. Start llm_monthly in the background (exits at once unless this month's LLM fundamental
#    scores are still missing; GPT-6.1 Sol via codex exec).
# 3. Large-cap momentum on its Alpaca PAPER account (execution/momentum_book.py): yesterday's
#    close -> market orders queued for today's open. Refuses once the market is open.
# 4. Download yesterday's minute file (ORB history, scanner scoring, QQQ noise bands).
# 5. Score past scanner logs against the true ORB pick.
# (Today's scanner capture is its own 09:20 job.) Log: data/logs/<date>-morning.log
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& uv run python -m horizon_trader.ops.jobs morning
$code = $LASTEXITCODE
# Task Scheduler has no OnFailure hook (systemd does): alert from here.
if ($code -ne 0) { & uv run python -m horizon_trader.ops.health --notify --failed morning }
exit $code
