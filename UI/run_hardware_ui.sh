#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${UICODE_PROJECT_DIR:-/home/cc/Desktop/UICode}"
VENV_DIR="${PROJECT_DIR}/.venv"
UI_ENTRY="${PROJECT_DIR}/UI/app.py"
REQUIREMENTS_FILE="${PROJECT_DIR}/UI/requirements.txt"

export DISPLAY=":0"
export XAUTHORITY="/home/cc/.Xauthority"
export PYTHONUNBUFFERED="1"
export PYGAME_HIDE_SUPPORT_PROMPT="1"

if [[ ! -f "${UI_ENTRY}" ]]; then
    echo "[UI] UI entrypoint not found: ${UI_ENTRY}" >&2
    exit 1
fi

if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
    echo "[UI] Requirements file not found: ${REQUIREMENTS_FILE}" >&2
    exit 1
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    if [[ -x /usr/bin/python3 ]]; then
        SYSTEM_PYTHON="/usr/bin/python3"
    else
        SYSTEM_PYTHON="$(command -v python3 || true)"
    fi
    if [[ -z "${SYSTEM_PYTHON}" ]]; then
        echo "[UI] System python3 was not found" >&2
        exit 1
    fi

    echo "[UI] Creating Python virtual environment: ${VENV_DIR}"
    if ! "${SYSTEM_PYTHON}" -m venv --system-site-packages "${VENV_DIR}"; then
        echo "[UI] Failed to create virtual environment." >&2
        echo "[UI] Install venv support, then retry:" >&2
        echo "[UI]   sudo apt install -y python3-venv" >&2
        exit 1
    fi
fi

VENV_PYTHON="${VENV_DIR}/bin/python"

if ! "${VENV_PYTHON}" -c "import pygame, numpy, cv2, serial" >/dev/null 2>&1; then
    echo "[UI] Installing Python dependencies from ${REQUIREMENTS_FILE}"
    if ! "${VENV_PYTHON}" -m pip install -r "${REQUIREMENTS_FILE}"; then
        echo "[UI] Python dependency installation failed" >&2
        exit 1
    fi
fi

if ! "${VENV_PYTHON}" -c "import lgpio" >/dev/null 2>&1; then
    echo "[UI] Raspberry Pi lgpio module is not available." >&2
    echo "[UI] Install the system package, then retry:" >&2
    echo "[UI]   sudo apt install -y python3-lgpio" >&2
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
exec "${VENV_PYTHON}" "${UI_ENTRY}" --backend hardware
