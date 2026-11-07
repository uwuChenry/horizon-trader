# Ops mini PC

**The mini runs Windows 11 Pro** (decided 2026-11-06): it uses the same Task Scheduler jobs
as the main PC (`deploy/windows/install_tasks.ps1`, every `.ps1` calls `ops.jobs`), plus login
checks and Discord/ntfy alerts (`ops/logins.py`, `ops/notify.py`). **Step-by-step checklist:
[`MINI_SETUP.md`](MINI_SETUP.md).** The role split, Syncthing, kill-switch and cutover rules
below apply to either OS; the systemd/IBC-on-Linux sections are the Ubuntu alternative, kept
working but not in use. On Windows, Task Scheduler has no OnFailure hook, so each job's `.ps1`
sends the failure alert itself.

## Ubuntu alternative

| Machine | Role | Responsibilities |
| --- | --- | --- |
| Mini PC | `HT_ROLE=ops` | IB Gateway, all scheduled jobs, `orb_live` when the owner decides, live dashboard. Sole writer of `data/live`, `data/journal`, `data/ibkr/options`, `data/llm/fundamental_scores`, `data/logs`. |
| Main Windows PC | `HT_ROLE=research` | Research, backtests, its own Massive download; receives the five ops folders read-only. **Do not run IB Gateway with the same paper user during market hours:** IBKR allows one session per user. |

**Until the mini is set up**, the main PC is the ops machine: keep `HT_ROLE=ops` in
its `.env` and the Task Scheduler jobs (`deploy/windows/install_tasks.ps1`; each
`.ps1` now calls `python -m horizon_trader.ops.jobs <job>`). Exactly one machine has
`HT_ROLE=ops` at any time.

## First-time setup

Use an Ubuntu user account with SSH access; run user services as that account, not
root. Keep the mini awake, enable time synchronization, and install Git, uv,
Node/npm (compatible with `web/package-lock.json`), `xvfb`, `xauth`, and restic.
Install Tailscale on both PCs and use the mini's Tailscale IP for SSH/dashboard
access. Install **both** LLM CLIs as this user and log in interactively: the journal
and the monthly fundamental scores run on GPT-6.1 Sol through the **Codex CLI**
(`codex exec`, the owner's ChatGPT login; verify `codex exec 'Reply OK'`), and
Claude Code (`claude -p 'Reply OK'`) is the fallback for `--model claude-...`.
The job units include `~/.local/bin` in `PATH`; put `codex` and `claude` there
(e.g. an npm prefix of `~/.local`) or adjust the unit PATH.

```bash
git clone <repository-url> ~/horizon-trader
cd ~/horizon-trader
git switch master
uv sync --locked --no-dev --group dashboard
cp .env.example .env
chmod 600 .env
mkdir -p data/live data/journal data/ibkr/options data/llm/fundamental_scores data/logs
(cd web && npm ci && npm run build)
```

Edit `.env` before starting any services. Use literal `KEY=value` entries, quote
values containing spaces or shell metacharacters, and use absolute paths (no
`export`, shell commands, `$HOME` expansion, or inline comments). systemd and the
backup script both read this file. Keep credentials out of Git and Syncthing.

| Keys | Mini PC values |
| --- | --- |
| `HT_ROLE` | `ops` |
| `IB_HOST`, `IB_PORT`, `IB_CLIENT_ID` | `127.0.0.1`, `4002`, an available client ID |
| `TWS_USERID`, `TWS_PASSWORD` | Paper login credentials, mapped into the installed IBC launcher as described below |
| `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` | Alpaca **paper** keys |
| `ALPACA_COMPETITION_AI_API_KEY`, `ALPACA_COMPETITION_AI_SECRET_KEY` | Competition paper account |
| `ALPACA_DAILY_BOOK_API_KEY`, `ALPACA_DAILY_BOOK_SECRET_KEY` | Daily-book paper account |
| `ALPACA_MOMENTUM_API_KEY`, `ALPACA_MOMENTUM_SECRET_KEY` | Large-cap momentum paper account (08:00 morning step) |
| `ALPACA_QQQ_NOISE_API_KEY`, `ALPACA_QQQ_NOISE_SECRET_KEY` | QQQ noise-area paper account (09:25 noise job) |
| `MASSIVE_API_KEY`, `MASSIVE_S3_ACCESS_KEY`, `MASSIVE_S3_SECRET_KEY` | REST and flat-file credentials; each machine downloads its own Massive data |
| `SEC_USER_AGENT` | Quoted application name and contact email |
| `NTFY_TOPIC` | Topic used by health/failure notifications; subscribe on the owner's device |
| `HT_DASHBOARD_HOST` | Mini's Tailscale IP; `127.0.0.1` for SSH tunneling. Never `0.0.0.0` on a public network: the dashboard has no login. |
| `RESTIC_REPOSITORY`, `RESTIC_PASSWORD_FILE` | Backup destination and absolute path to a protected password file; backend credentials as needed |

The clone and `.venv` must be `~/horizon-trader` and `~/horizon-trader/.venv`.
Do not use `deploy/linux/uv.sh` for this setup: it intentionally selects a
different venv for a checkout shared with Windows. Leave `HT_DATA_DIR` unset so
jobs, backups, and sync agree on the five paths above.

### IB Gateway / IBC

Install the paper Gateway and IBC, then adapt
[`ib-gateway.service`](systemd/ib-gateway.service). Its paths
`~/ibc/gatewaystart.sh` and `~/Jts` are placeholders. Verify the installed IBC
release's launcher, Gateway major version, `IBC_PATH`, `IBC_INI`, `TWS_PATH`,
and settings directory before enabling the service. The launcher must run in
the foreground (`-inline`) under `xvfb-run`.

Verify `TradingMode=paper`, API port **4002** (`OverrideTwsApiPort=4002` where
supported), read-only API **off** (`ReadOnlyApi=no`), and `AutoRestartTime`
before **07:45 ET**. Check Gateway/JVM time zone and DST behavior; the unit sets
`TZ=America/New_York`. Check these settings against the
[installed version's IBC config documentation](https://github.com/IbcAlpha/IBC/blob/master/resources/config.ini).
Weekly 2FA is manual; arrange access to the Gateway display when needed.

The [upstream launcher](https://github.com/IbcAlpha/IBC/blob/master/resources/gatewaystart.sh)
does not automatically read `TWS_USERID` / `TWS_PASSWORD`. In the local launcher,
map its credential assignments to `TWSUSERID="${TWS_USERID}"` and
`TWSPASSWORD="${TWS_PASSWORD}"`, and set `TRADING_MODE=paper`; verify this mapping
against the installed release. The unit supplies `.env` to the process. Do not
embed credentials in this repository. Xvfb supplies a display, not remote
desktop access or automatic 2FA.

Prepare units without starting schedules:

```bash
bash deploy/linux/install.sh --units-only
systemd-analyze --user verify ~/.config/systemd/user/ht-*.service \
  ~/.config/systemd/user/ht-*.timer ~/.config/systemd/user/ib-gateway.service
```

Wait for the cutover checklist before running `bash deploy/linux/install.sh
--with-gateway`. That command copies units/drop-ins, enables linger, and starts
all timers, dashboard, and Gateway. Omit `--with-gateway` to manage Gateway
separately. Re-running is safe; omitting the flag does not stop an already
enabled Gateway. If linger needs administrator authorization, run
`sudo loginctl enable-linger "$USER"` once, then rerun the installer as yourself.
If the old placeholder was installed system-wide, disable it with
`sudo systemctl disable --now horizon-trader.timer horizon-trader.service`;
the installer only removes obsolete **user** units.

### One-time data copy from the main PC

Besides the five ops folders (moved at cutover, below), copy these once; they
are research data, never synced afterwards:

| Folder | Size (Nov 2026) | Needed by |
| --- | --- | --- |
| `data/massive` | ~33 GB | momentum (day files, market caps, splits), noise bands and scanner scoring (minute files), ORB. Re-downloading 5 years on Starter is slow; copy over the LAN or a USB disk |
| `data/sec` | ~180 MB | monthly LLM fundamental scores (first trading day of the month) |

After the copy, `massive download --dataset day` and `--dataset minute` only
fetch the missing days. Verify with `.venv/bin/python -m horizon_trader.intraday.noise_live check`
and `.venv/bin/python -m horizon_trader.execution.momentum_book run --dry-run`.

## Deploy workflow

Work on a branch, merge to `master`, push, then deploy to the mini:

```bash
ssh mini ~/horizon-trader/deploy/linux/deploy.sh
# If the Git checkout lacks executable script modes (e.g. merged on Windows):
ssh mini 'bash ~/horizon-trader/deploy/linux/deploy.sh'
```

Run one of these commands. Deploy requires `master` and a clean tree, including
untracked files. It refuses weekdays **09:24 <= time < 16:05 ET**; `--force`
overrides only the time guard. Prefer after the evening work finishes, and check
for running jobs, including monthly scoring, before updating their environment.

The script records HEAD, pulls with `--ff-only`, syncs locked ops/dashboard
dependencies, temporarily syncs the locked dev group for pytest/httpx, and runs
`uv run --no-sync pytest -q`. Failed checks reset to the old commit, restore its
ops dependencies, and exit 1. Success removes the test dependencies, rebuilds
`web/dist` with `npm ci && npm run build` when npm is available, copies/reloads
units, restarts the dashboard, and appends UTC time, commit, and subject to
`data/live/deploys.log`. Missing npm emits a warning and keeps the existing
frontend; the first setup must build it. Later build/reload/restart failures
stop deployment without recording success; automatic rollback covers the test
stage. Deploy does not enable timers or start Gateway.

## Schedule and checks

All times are **America/New_York**, including DST. Trading jobs skip non-trading
days themselves; systemd timers select weekdays only.

| Timer / job | Time | Catch up after downtime? |
| --- | --- | --- |
| `ht-morning` / `morning` | Mon-Fri 08:00 | Yes: downloads are safe to catch up; the momentum step refuses once the market is open |
| `ht-scanner` / `scanner` | Mon-Fri 09:20 | No: the 09:25/09:35 lists cannot be recovered |
| `ht-observe` / `observe` | Mon-Fri 09:24 | No: late observations cannot recover the session |
| `ht-noise` / `noise` | Mon-Fri 09:25 (to ~16:05) | No: joining mid-session skips the rule's earlier checks |
| `ht-journal` / `journal` | Mon-Fri 15:00 | No: late forecasts/quotes are wrong |
| `ht-options_log` / `options_log` | Mon-Fri 15:35 | No: missed intraday quotes are unrecoverable |
| `ht-evening` / `evening` | Mon-Fri 18:00 | Yes: after-close processing is safe to catch up |
| `ht-health` | Mon-Fri 18:30 | Yes: current health is still useful |
| `ht-backup` | Daily 19:00 | Yes: back up current data |

`morning` launches `llm_monthly` in the background itself; there is no monthly
timer. Its drop-in preserves that child after the parent exits, so stopping
`ht-job@morning.service` does **not** stop monthly scoring. Other jobs time out
after 3h; noise gets 8h; observe gets 7h and restarts on failure after 120 seconds, with four
starts allowed per 8h. Inspect failures before using
`systemctl --user reset-failed ht-job@observe.service` to clear that limit.
`orb_live` is not scheduled: only the owner decides when to run it.

```bash
systemctl --user list-timers 'ht-*'
systemctl --user status ht-dashboard.service ib-gateway.service
journalctl --user -u ht-job@morning.service -n 100 --no-pager
.venv/bin/python -m horizon_trader.ops.jobs morning --dry
.venv/bin/python -m horizon_trader.ops.health --notify
.venv/bin/python -m horizon_trader.ops.health --notify --failed morning
```

Job logs are `data/logs/<date>-*.log`. Failures trigger `ht-notify@<job>.service`
with the log tail; `NTFY_TOPIC` is required for delivery. The dashboard is at
`http://<mini-tailscale-ip>:8501` and needs the built `web/dist`.

## Syncthing: mini to main only

Create exactly five shared folders, rooted at `data/live`, `data/journal`,
`data/ibkr/options`, `data/llm/fundamental_scores`, and `data/logs`. Set each to
**Send Only** on the mini and **Receive Only** on the main. Treat the main's
copies as read-only; receive-only mode does not prevent local edits, it prevents
them propagating back. Correct any reported local changes instead of using the
main as another writer. **Never sync `data/massive`**; each machine downloads its
own copy. Do not share the whole repository or `.env` as a shortcut.

## Backups

Set `RESTIC_REPOSITORY` and `RESTIC_PASSWORD_FILE` in `.env`, protect the password
file with mode 600, and initialize the repository once. Use a destination off
the mini and retain the password separately. From the clone:

```bash
export RESTIC_REPOSITORY=... RESTIC_PASSWORD_FILE=...   # same values as .env
restic init                         # only for a new backup repository
bash deploy/linux/backup.sh
restic snapshots
restic check
```

The daily backup includes the five ops folders that exist (the script reads only
the two `RESTIC_*` keys from `.env`) and keeps **14 daily, 8 weekly, 24 monthly**
snapshots, then prunes. Missing configuration skips with exit 0 and a message;
configured backup errors fail the service and trigger a push. Syncthing is
not a backup. Periodically restore a snapshot into a separate directory and
check it; do not restore over active ledgers.

## Kill switch

**Run `--kill` ON THE MINI.** The `data/live/KILL` file is per machine; creating
it on the receive-only research PC does not protect the ops process.

```bash
ssh mini 'cd ~/horizon-trader && .venv/bin/python -m horizon_trader.run_daily --kill'
```

This writes KILL before trying to cancel open IBKR and configured Alpaca orders.
Check cancellation results and broker state; leave KILL in place until the
owner deliberately resumes.

## Cutover checklist

- [ ] Finish setup/build/configuration on the mini, with its timers still stopped.
- [ ] Cut over **after the main PC's 18:00 evening run finishes**. Confirm no job
      or monthly scoring process is still writing the ops folders.
- [ ] Unregister Windows tasks in PowerShell:
      `Unregister-ScheduledTask -TaskName "horizon-trader *" -Confirm:$false`.
- [ ] Stop Gateway on the main. Copy all five ops folders to the mini, retaining
      any KILL file; verify the copy before configuring one-way Syncthing.
      Each Alpaca ledger pins its account (`data/live/*/alpaca_account.json`) and
      reconciles against it, so the copied ledgers must be the latest ones.
- [ ] Set `HT_ROLE=research` on the main and `HT_ROLE=ops` on the mini.
- [ ] Verify IBC paper settings, credentials, display access, and manual 2FA on
      the mini. Check dashboard access over Tailscale and backup configuration.
- [ ] If timers were rehearsed previously, stop the morning/evening timers and
      clear their catch-up timestamps before enabling:
      `systemctl --user stop ht-morning.timer ht-evening.timer`, then
      `systemctl --user clean --what=state ht-morning.timer ht-evening.timer`.
- [ ] Run `bash ~/horizon-trader/deploy/linux/install.sh --with-gateway` on the
      mini (omit the flag if Gateway is managed separately). Verify
      `systemctl --user list-timers 'ht-*'` and
      `loginctl show-user "$USER" -p Linger`.
- [ ] Confirm the **first scheduled trading job is the next weekday 08:00**
      morning run (holidays skip). Health/backup may run earlier. Check that
      first run's logs, ntfy delivery, dashboard data, and read-only sync.
