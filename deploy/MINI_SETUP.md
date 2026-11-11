# Mini PC setup checklist (Windows 11 Pro ops machine)

Tick each box as you go. The mini becomes the **only** machine that trades or writes
forward-test state (`HT_ROLE=ops`); the main PC becomes research only. Background and the
Ubuntu alternative: [`README.md`](README.md).

**Timing.** Do parts 1-6 any time with the mini's tasks *not* installed. Do part 7 (cutover)
on a **weekend**, after the main PC's Friday 18:00 evening run, so no job runs while two
machines hold the state. The first trading job on the mini is then Monday 08:00.

---

## 1. Windows settings (mini)

- [ ] Time zone **Eastern Time (US & Canada)**; Settings > Time > *Set time automatically* on.
      Check against a web clock: `curl.exe -sI https://www.google.com | findstr Date` (GMT).
- [ ] Power: screen off is fine, **sleep = never**, hibernate off (`powercfg /h off`, admin).
- [ ] BIOS/UEFI: power on after AC power loss.
- [ ] Windows Update: active hours 07:00-19:00, and `gpedit.msc` > Computer Configuration >
      Administrative Templates > Windows Components > Windows Update > **Legacy Policies** >
      *No auto-restart with logged on users for scheduled automatic updates installations* =
      Enabled (Windows 11 24H2+ moved it into Legacy Policies). It only applies while
      *Manage end user experience > Configure Automatic Updates* is Enabled (option 4,
      auto download and schedule install).
- [ ] **Auto-logon** for the account that will run everything: `winget install
      Microsoft.Sysinternals.Autologon`, open a **new** terminal, run `autologon`, enter user / domain (the PC name) /
      password (the Microsoft-account password, not the PIN), Enable. Then lock the screen
      (Win+L). Tasks run only while this user is logged on.
- [ ] Remote Desktop on (Settings > System > Remote Desktop). Disconnect RDP sessions by
      closing the window, never *Sign out*: signing out stops the Gateway and every job.
- [ ] Tailscale installed and logged in on **both** PCs; note the mini's Tailscale IP.

## 2. Tools (mini, as the auto-logon user)

- [ ] Git and Node LTS: `winget install Git.Git OpenJS.NodeJS.LTS`
- [ ] uv: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- [ ] Codex CLI: `npm install -g @openai/codex`, then `codex login` (ChatGPT account).
      Verify: `codex login status` says *Logged in using ChatGPT*.
- [ ] Claude Code installed and logged in. Verify: `claude auth status` shows `"loggedIn": true`.
- [ ] Open a **new** terminal and check all of them are on PATH:
      `git --version; node --version; uv --version; codex --version; claude --version`

## 3. IB Gateway + IBC (mini)

- [ ] IB Gateway **stable** installed (IBKR website, offline installer).
- [ ] IBC for Windows (github.com/IbcAlpha/IBC releases), set up per its user guide, with
      `config.ini`: `TradingMode=paper`, paper login, `ReadOnlyApi=no`,
      `OverrideTwsApiPort=4002`, `AcceptIncomingConnectionAction=accept`, and a daily
      `AutoRestartTime` before 07:30 (e.g. `06:45 AM`) so one weekly 2FA lasts all week.
      `config.ini` holds the password in plain text: keep it out of the repo.
- [ ] A Task Scheduler task *At log on* that runs IBC's `StartGateway.bat`.
- [ ] If you use Remote Desktop: from an elevated PowerShell run
      `deploy\windows\install_rdp_console.ps1`. Gateway can't start in a disconnected RDP
      session (no display, `HeadlessException`), so this moves the session to the console on
      disconnect. Needs a monitor or dummy plug that stays detected; the desktop is left
      unlocked on it.
- [ ] Log in once and approve the 2FA prompt in IBKR Mobile.
- [ ] **Never run the paper Gateway on both PCs at once**: IBKR allows one session per user.

## 4. Repo, .env, data (mini)

- [ ] Clone and build (any path works; the scripts locate the repo themselves):
      ```powershell
      git clone https://github.com/uwuChenry/horizon-trader.git C:\horizon-trader
      cd C:\horizon-trader; git switch master; uv sync
      cd web; npm ci; npm run build; cd ..
      ```
- [ ] Copy `.env` from the main PC by hand (USB or RDP clipboard; never git or Syncthing),
      then change on the mini:
  - [ ] `HT_ROLE=ops`
  - [ ] `HT_DASHBOARD_HOST=<mini's Tailscale IP>`
  - [ ] `DISCORD_WEBHOOK_URL=` and `DISCORD_USER_ID=` (part 5)
  - [ ] keys already there: `IB_*`, all five `ALPACA_*` pairs (default, COMPETITION_AI,
        DAILY_BOOK, MOMENTUM, QQQ_NOISE; all paper `PK...`), `MASSIVE_*`, `SEC_USER_AGENT`
- [ ] Copy research data from the main PC once (USB disk, or `robocopy <src> <dst> /E /MT:16`
      over a share): `data\massive` (~33 GB), `data\sec` (~180 MB). The ops folders come at
      cutover (part 7), not now.

## 5. Discord alerts

- [ ] A private Discord server (or channel) for alerts, e.g. `#horizon-alerts`.
- [ ] Channel settings > Integrations > Webhooks > New Webhook > *Copy Webhook URL* into
      `DISCORD_WEBHOOK_URL`. Treat it as a password.
- [ ] Settings > Advanced > Developer Mode on; right-click yourself > *Copy User ID* into
      `DISCORD_USER_ID`.
- [ ] Phone: Discord app notifications on for that server (at least @mentions).
- [ ] Test (should ping your phone):
      `uv run python -m horizon_trader.ops.notify "test alert" "hello from the mini" urgent`

## 6. Smoke tests (mini; nothing here places orders)

- [ ] `uv run pytest -q`: all pass.
- [ ] `uv run python -m horizon_trader.ops.logins --canary`: four `ok` lines (IB Gateway
      `DU...`, Codex login, Claude login, Codex canary). *Before cutover the Gateway line
      fails if the main PC's Gateway holds the session; that's expected.*
- [ ] `uv run python -m horizon_trader.execution.alpaca_check`: Alpaca paper reachable.
- [ ] `uv run python -m horizon_trader.intraday.noise_live check`: today's bands print.
- [ ] `uv run python -m horizon_trader.execution.momentum_book run --dry-run`: 10 targets.
- [ ] `uv run python -m horizon_trader.ops.jobs morning --dry`: 5 steps, `run=True`.
- [ ] `uv run python -m horizon_trader.ops.health`: prints every check (stale ledgers are
      expected until the cutover copy).
- [ ] `uv run python -m horizon_trader.dashboard`, then open `http://<tailscale-ip>:8501`
      from your phone or the main PC; stop it with Ctrl+C.

## 7. Cutover (weekend)

On the **main PC**:
- [ ] Friday's 18:00 evening run has finished (`data\logs\<Friday>-evening.log` ends with
      `sent N orders` lines) and nothing is running.
- [ ] Remove every task: `Unregister-ScheduledTask -TaskName "horizon-trader *" -Confirm:$false`
- [ ] Quit IB Gateway (and disable its auto-start if it has one).
- [ ] Copy the five ops folders to the mini, replacing the mini's copies: `data\live`,
      `data\journal`, `data\ibkr\options`, `data\llm\fundamental_scores`, `data\logs`.
      They must be the latest: each Alpaca ledger reconciles against its account.
- [ ] Delete the `HT_ROLE=ops` line from the main PC's `.env` (unset = research = refuses
      orders).

On the **mini**:
- [ ] Gateway logged in (`uv run python -m horizon_trader.ops.logins` all `ok`).
- [ ] `git pull` (latest master), `uv sync`.
- [ ] `powershell -ExecutionPolicy Bypass -File deploy\windows\install_tasks.ps1`
      (all tasks, the observer and the dashboard).
- [ ] Check: `Get-ScheduledTask -TaskName "horizon-trader *" | Get-ScheduledTaskInfo | Select TaskName, NextRunTime`
      shows 11 tasks with sensible next runs (logins Sunday 07:30 or Monday 07:30, morning
      Monday 08:00).
- [ ] Optional: Syncthing on both PCs for the five ops folders, **Send Only** on the mini,
      **Receive Only** on the main PC, so the main PC's dashboard shows live results.

## 8. First trading day (Monday)

- [ ] 07:30 no Discord alert (silent = logins ok; `data\logs\<date>-logins.log` to confirm).
- [ ] 08:00 `data\logs\<date>-morning.log`: Massive downloads, then momentum sends its first
      orders for the open.
- [ ] 09:20-09:36 `...-scanner.log` captured; 09:25 `...-noise.log` started.
- [ ] 15:00 journal + competition logs; 15:35 `...-options.log` (`12/12 underlyings`).
- [ ] 18:00 evening log; **18:30 Discord "all N checks OK"** (or a list of problems).
- [ ] Dashboard Live page shows all ledgers, including `momentum_top10_alpaca_paper`.

## Weekly / when pinged

- **IBKR 2FA:** about once a week (usually Sunday/Monday) the Gateway needs a fresh login.
  The 07:30 check pings you; RDP in and approve in IBKR Mobile before 08:00.
- **Codex/Claude login dead:** run `codex login` / `claude` > /login on the mini, then
  `uv run python -m horizon_trader.ops.logins --canary`.
- **Kill switch:** run it *on the mini* (RDP or SSH):
  `uv run python -m horizon_trader.run_daily --kill`. The `data\live\KILL` file is per machine.
- **Updating code:** develop on the main PC, push to master, then on the mini after 16:05 ET
  (or a weekend): `git pull; uv sync; uv run pytest -q`.
