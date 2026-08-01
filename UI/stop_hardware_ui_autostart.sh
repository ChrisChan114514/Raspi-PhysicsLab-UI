#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="raspi-ui.service"

if [[ "${EUID}" -ne 0 ]]; then
    exec sudo -- "$0" "$@"
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "[UI] systemctl is unavailable; this script must run on the Raspberry Pi." >&2
    exit 1
fi

if ! systemctl cat "${SERVICE_NAME}" >/dev/null 2>&1; then
    echo "[UI] ${SERVICE_NAME} is not installed." >&2
    exit 1
fi

systemctl disable --now "${SERVICE_NAME}"
systemctl reset-failed "${SERVICE_NAME}"

echo "[UI] ${SERVICE_NAME} has stopped and is disabled at boot."
echo "[UI] To enable it again: sudo systemctl enable --now ${SERVICE_NAME}"
