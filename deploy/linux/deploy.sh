#!/usr/bin/env bash
set -euo pipefail

# Parse the complete deployment before git pull can replace this script on disk.
main() {
    force=false
    for arg in "$@"; do
        case "$arg" in
            --force) force=true ;;
            -h|--help) echo "Usage: $0 [--force]"; exit 0 ;;
            *) echo "Unknown argument: $arg" >&2; exit 2 ;;
        esac
    done

    repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
    cd -- "$repo_dir"
    # SSH commands need not load the interactive shell's PATH.
    export PATH="$HOME/.local/bin:$PATH"
    export UV_PROJECT_ENVIRONMENT="$repo_dir/.venv"

    branch="$(git branch --show-current)"
    if [[ "$branch" != master ]]; then
        echo "Refusing deploy: check out master first." >&2
        exit 1
    fi
    tree_status="$(git status --porcelain --untracked-files=all)"
    if [[ -n "$tree_status" ]]; then
        echo "Refusing deploy: the working tree must be clean (including untracked files)." >&2
        exit 1
    fi

    # Read weekday and clock together to avoid a midnight boundary race.
    read -r weekday hhmm <<< "$(TZ=America/New_York date '+%u %H%M')"
    clock_hhmm=$((10#$hhmm))
    if ! $force && (( weekday <= 5 && clock_hhmm >= 924 && clock_hhmm < 1605 )); then
        echo "Refusing deploy: weekdays 09:24-16:05 America/New_York; use --force to override." >&2
        exit 1
    fi

    old_commit="$(git rev-parse HEAD)"
    git pull --ff-only
    uv sync --locked --no-dev --group dashboard
    # pytest and httpx are in dev. Temporarily install the locked test dependencies;
    # the exact ops sync above removes them, so --no-sync alone cannot run tests.
    if ! uv sync --locked --group dev --group dashboard || ! uv run --no-sync pytest -q; then
        echo "Deployment checks failed; restoring $old_commit and its ops environment." >&2
        git reset --hard "$old_commit"
        uv sync --locked --no-dev --group dashboard
        exit 1
    fi
    uv sync --locked --no-dev --group dashboard

    if command -v npm >/dev/null 2>&1; then
        (cd web && npm ci && npm run build)
    else
        echo "WARNING: npm is unavailable; web/dist was not rebuilt. Install Node/npm before first use." >&2
    fi

    bash "$repo_dir/deploy/linux/install.sh" --units-only
    systemctl --user restart ht-dashboard.service
    mkdir -p data/live
    printf '%s %s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        "$(git rev-parse HEAD)" "$(git log -1 --format=%s)" >> data/live/deploys.log
    echo "Deployed $(git rev-parse --short HEAD)."
}

main "$@"
