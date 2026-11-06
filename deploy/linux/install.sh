#!/usr/bin/env bash
set -euo pipefail

with_gateway=false
units_only=false
for arg in "$@"; do
    case "$arg" in
        --with-gateway) with_gateway=true ;;
        --units-only) units_only=true ;;
        -h|--help)
            echo "Usage: $0 [--with-gateway | --units-only]"
            echo "--units-only copies units and reloads systemd without enabling services/timers."
            exit 0
            ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done
if $with_gateway && $units_only; then
    echo "--with-gateway and --units-only cannot be combined." >&2
    exit 2
fi

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
unit_dir="$HOME/.config/systemd/user"
mkdir -p -- "$unit_dir"

# Remove only the superseded user units, if installed by an older setup.
if [[ -e "$unit_dir/horizon-trader.timer" || -L "$unit_dir/horizon-trader.timer" ]]; then
    systemctl --user disable --now horizon-trader.timer
fi
if [[ -e "$unit_dir/horizon-trader.service" || -L "$unit_dir/horizon-trader.service" ]]; then
    systemctl --user stop horizon-trader.service
fi
rm -f -- "$unit_dir/horizon-trader.timer" "$unit_dir/horizon-trader.service"
cp -R -- "$repo_dir/deploy/systemd/." "$unit_dir/"

if ! $units_only; then
    loginctl enable-linger "$USER"
fi
systemctl --user daemon-reload

if ! $units_only; then
    timers=()
    for timer in "$repo_dir"/deploy/systemd/ht-*.timer; do
        timers+=("$(basename -- "$timer")")
    done
    systemctl --user enable --now "${timers[@]}" ht-dashboard.service
    if $with_gateway; then
        systemctl --user enable --now ib-gateway.service
    fi
fi

systemctl --user list-timers 'ht-*'
