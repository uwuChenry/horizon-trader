# Monthly LLM fundamental scores (research/llm_fundamentals, GPT-6.1 Sol via codex exec): started in the background by
# morning.ps1 after the Massive day download. Runs only when the current month has no run yet,
# so it fires on the month's first weekday morning and catches up the next morning if the PC
# was off. Never back-dates: the as-of date is always today. Needs this user's Codex (ChatGPT) login.
# Log: data/logs/<date>-llm-fundamentals.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$month = Get-Date -Format yyyy-MM
if (Get-ChildItem "data/llm/fundamental_scores" -Directory -Filter "$month-*" -ErrorAction SilentlyContinue) {
    exit 0  # this month is done (or started: export refuses to overwrite)
}
New-Item -ItemType Directory -Force "data/logs" | Out-Null
$log = "data/logs/$(Get-Date -Format yyyy-MM-dd)-llm-fundamentals.log"
foreach ($cmd in @("export", "run", "check")) {
    "=== $(Get-Date -Format HH:mm:ss) $cmd" | Out-File -Append -Encoding utf8 $log
    & uv run python -m horizon_trader.llm.fundamentals $cmd *>&1 | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) { "=== stopped: $cmd failed" | Out-File -Append -Encoding utf8 $log; exit 1 }
}
"=== $(Get-Date -Format HH:mm:ss) done" | Out-File -Append -Encoding utf8 $log
