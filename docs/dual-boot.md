# Sharing the checkout between Windows and Ubuntu 22.04

Windows location: `D:\github\horizon-trader`. Ubuntu accesses the same files by
mounting the Data NTFS volume. The source, Git history, `.env`, research, and
`data/` directory can be shared. Python environments must be separate:

- Windows uses `.venv` inside the checkout.
- Ubuntu uses `~/.local/share/horizon-trader/venv` on its Linux filesystem.
  `deploy/linux/uv.sh` sets this location for each command. If `XDG_DATA_HOME`
  is set, it uses that directory instead of `~/.local/share`. Set `HT_LINUX_ENV`
  to an absolute Linux filesystem path to override it.

## Windows

```powershell
cd D:\github\horizon-trader
uv sync --locked
uv run python -m horizon_trader.dashboard
```

Open this new folder in your editor. Virtual environments must be rebuilt when
relocating a checkout because installed scripts and editable packages can refer
to the old absolute path.

Windows Task Scheduler registrations also contain absolute script paths. The
morning, evening, and observation tasks need to point at the new checkout.
Those tasks only run while Windows is booted.

## Ubuntu

Mount the Data volume in Files or Disks. Find its actual mount point with
`lsblk -f` or `findmnt`; `/media/$USER/Data` below is an example. Configure a
stable mount point in Disks if you plan to schedule Linux jobs.

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
```

Then use the wrapper for every project command on Ubuntu:

```bash
cd "/media/$USER/Data/github/horizon-trader"  # adjust to the actual mount point
bash deploy/linux/uv.sh sync --locked
bash deploy/linux/uv.sh run pytest -q
bash deploy/linux/uv.sh run python -m horizon_trader.dashboard
```

The project pins Python 3.12; uv can install it independently of Ubuntu 22.04's
system Python. For optional research dependencies:

```bash
bash deploy/linux/uv.sh sync --locked --group research
```

Avoid a plain `uv sync` or `uv run` on Ubuntu in this shared checkout: without
the wrapper, uv would target Windows' `.venv`. The wrapper keeps its environment
setting local to that command, so other projects are unaffected. See
[uv's environment configuration](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path).

The existing `.env` is preserved; do not overwrite it with `.env.example`.
Any user-level credentials and IB Gateway installation/login must be configured
separately on Ubuntu. The dashboard and local research can run without Gateway.

If configuring `deploy/systemd/horizon-trader.service` later, set its `User` and
`WorkingDirectory` to your Ubuntu user and the mounted checkout, add
`Environment=UV_PROJECT_ENVIRONMENT=/home/YOUR_USER/.local/share/horizon-trader/venv`,
and adjust the uv executable path. Ensure the data volume is mounted before
the service runs. Windows scheduled jobs are not automatically installed there.

## Switching operating systems

Close project processes before switching and shut Windows down fully. Keep
Windows Fast Startup disabled: a hibernated NTFS volume can be read-only under
Ubuntu. Do not force-write a hibernated volume. See the
[Ubuntu NTFS driver documentation](https://manpages.ubuntu.com/manpages/jammy/man8/mount.ntfs.8.html).

The repository's `.gitattributes` already specifies LF for source files and
CRLF for PowerShell scripts. If Linux Git reports executable-bit changes on
NTFS, use `git config core.fileMode false` in this repository. If Git reports
an ownership error, add only this exact checkout path as a `safe.directory`;
do not disable that check globally with a wildcard.
