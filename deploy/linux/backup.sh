#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$repo_dir"

# Read only the two restic keys from .env: sourcing the whole file would export every secret
# and break on any value bash can't parse.
env_value() {
    [[ -f .env ]] || return 0
    sed -n "s/^$1=//p" .env | tail -n 1 | tr -d '"'"'"
}
RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-$(env_value RESTIC_REPOSITORY)}"
RESTIC_PASSWORD_FILE="${RESTIC_PASSWORD_FILE:-$(env_value RESTIC_PASSWORD_FILE)}"
if [[ -z "${RESTIC_REPOSITORY:-}" || -z "${RESTIC_PASSWORD_FILE:-}" ]]; then
    echo "Backup skipped: set RESTIC_REPOSITORY and RESTIC_PASSWORD_FILE in .env."
    exit 0
fi
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
if ! command -v restic >/dev/null 2>&1; then
    echo "Backup is configured but restic is not installed." >&2
    exit 1
fi
if [[ ! -r "$RESTIC_PASSWORD_FILE" ]]; then
    echo "Backup password file is not readable: $RESTIC_PASSWORD_FILE" >&2
    exit 1
fi

# Only folders that exist: restic marks the snapshot incomplete (exit 3) for missing paths.
paths=()
for p in data/live data/journal data/ibkr/options data/llm/fundamental_scores data/logs; do
    if [[ -e "$p" ]]; then paths+=("$p"); fi
done
if (( ${#paths[@]} == 0 )); then
    echo "Backup skipped: no ops folders under data/ yet."
    exit 0
fi
restic backup -- "${paths[@]}"
restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 24 --prune
