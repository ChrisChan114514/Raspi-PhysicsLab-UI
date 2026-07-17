#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/cc/Desktop/UICode"
VENV_DIR="${PROJECT_DIR}/.venv"
UI_ENTRY="${PROJECT_DIR}/UI/app.py"

export DISPLAY=":0"
export XAUTHORITY="/home/cc/.Xauthority"
export PYTHONUNBUFFERED="1"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    echo "[UI] Python virtual environment not found: ${VENV_DIR}" >&2
    exit 1
fi

if [[ ! -f "${UI_ENTRY}" ]]; then
    echo "[UI] UI entrypoint not found: ${UI_ENTRY}" >&2
    exit 1
fi

for ((attempt = 1; attempt <= 60; attempt++)); do
    if [[ -S /tmp/.X11-unix/X0 && -r "${XAUTHORITY}" ]]; then
        break
    fi
    if ((attempt == 1)); then
        echo "[UI] Waiting for display ${DISPLAY} and ${XAUTHORITY}"
    fi
    sleep 1
done

if [[ ! -S /tmp/.X11-unix/X0 || ! -r "${XAUTHORITY}" ]]; then
    echo "[UI] Display ${DISPLAY} was not ready within 60 seconds" >&2
    exit 1
fi

cd "${PROJECT_DIR}"
source "${VENV_DIR}/bin/activate"

echo "[UI] Starting hardware UI on ${DISPLAY}"
exec "${VENV_DIR}/bin/python" "${UI_ENTRY}" --backend hardware
