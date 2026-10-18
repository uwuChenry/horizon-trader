#!/usr/bin/env bash
# Use a Linux-native environment while sharing the checkout with Windows.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$repo_dir"
export UV_PROJECT_ENVIRONMENT="${HT_LINUX_ENV:-${XDG_DATA_HOME:-$HOME/.local/share}/horizon-trader/venv}"
exec uv "$@"
