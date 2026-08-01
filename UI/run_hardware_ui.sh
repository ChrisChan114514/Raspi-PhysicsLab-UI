#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${UI_SERVICE_NAME:-raspi-ui.service}"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"

SCRIPT_PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd -- "$(dirname -- "${SCRIPT_PATH}")" && pwd)"
DEFAULT_PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

PROJECT_DIR="${UICODE_PROJECT_DIR:-${DEFAULT_PROJECT_DIR}}"
VENV_DIR="${PROJECT_DIR}/.venv"
UI_ENTRY="${PROJECT_DIR}/UI/app.py"
REQUIREMENTS_FILE="${PROJECT_DIR}/UI/requirements.txt"

default_service_user() {
    if [[ -n "${UI_SERVICE_USER:-}" ]]; then
        printf '%s\n' "${UI_SERVICE_USER}"
    elif [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        printf '%s\n' "${SUDO_USER}"
    else
        printf '%s\n' "cc"
    fi
}

SERVICE_USER="$(default_service_user)"
SERVICE_GROUP="${UI_SERVICE_GROUP:-${SERVICE_USER}}"
SERVICE_USER_HOME="$(getent passwd "${SERVICE_USER}" 2>/dev/null | awk -F: '{print $6}' || true)"
if [[ -z "${SERVICE_USER_HOME}" ]]; then
    SERVICE_USER_HOME="/home/${SERVICE_USER}"
fi

XAUTHORITY_PATH="${UI_XAUTHORITY:-${SERVICE_USER_HOME}/.Xauthority}"
DISPLAY_CANDIDATES="${UI_DISPLAY_CANDIDATES:-:0 :1 :2}"
DISPLAY_WAIT_SECONDS="${UI_DISPLAY_WAIT_SECONDS:-90}"
UI_EXTRA_ARGS="${UI_EXTRA_ARGS:-}"
SERVICE_USER_UID="$(id -u "${SERVICE_USER}" 2>/dev/null || true)"
if [[ -z "${SERVICE_USER_UID}" ]]; then
    SERVICE_USER_UID="1000"
fi

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export PYGAME_HIDE_SUPPORT_PROMPT="${PYGAME_HIDE_SUPPORT_PROMPT:-1}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"

usage() {
    cat <<EOF
Usage:
  ${SCRIPT_PATH} [start|install|enable|restart|stop|disable|status|logs|verify|uninstall]

Commands:
  start      Start the hardware UI in the foreground. This is the default.
  install    Install/update ${SERVICE_NAME}, but do not start it.
  enable     Install/update ${SERVICE_NAME}, enable boot autostart, and start now.
  restart    Restart the systemd service.
  stop       Stop the systemd service.
  disable    Stop and disable boot autostart.
  status     Show systemd service status.
  logs       Follow systemd service logs.
  verify     Print boot/service/display diagnostics.
  uninstall  Disable and remove the systemd service file.

Useful environment overrides:
  UICODE_PROJECT_DIR       Current: ${PROJECT_DIR}
  UI_SERVICE_USER          Current: ${SERVICE_USER}
  UI_DISPLAY_CANDIDATES    Current: ${DISPLAY_CANDIDATES}
  UI_XAUTHORITY            Current: ${XAUTHORITY_PATH}
  UI_EXTRA_ARGS            Example: "--debug-sensor"
EOF
}

require_root() {
    local command_name="$1"
    shift || true
    if [[ "${EUID}" -eq 0 ]]; then
        return 0
    fi
    exec sudo env \
        "UICODE_PROJECT_DIR=${PROJECT_DIR}" \
        "UI_SERVICE_NAME=${SERVICE_NAME}" \
        "UI_SERVICE_USER=${SERVICE_USER}" \
        "UI_SERVICE_GROUP=${SERVICE_GROUP}" \
        "UI_XAUTHORITY=${XAUTHORITY_PATH}" \
        "UI_DISPLAY_CANDIDATES=${DISPLAY_CANDIDATES}" \
        "UI_DISPLAY_WAIT_SECONDS=${DISPLAY_WAIT_SECONDS}" \
        "UI_EXTRA_ARGS=${UI_EXTRA_ARGS}" \
        "SDL_VIDEODRIVER=${SDL_VIDEODRIVER}" \
        /bin/bash "${SCRIPT_PATH}" "${command_name}" "$@"
}

ensure_project_files() {
    if [[ ! -f "${UI_ENTRY}" ]]; then
        echo "[UI] UI entrypoint not found: ${UI_ENTRY}" >&2
        exit 1
    fi

    if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
        echo "[UI] Requirements file not found: ${REQUIREMENTS_FILE}" >&2
        exit 1
    fi
}

ensure_python_env() {
    if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
        local system_python
        if [[ -x /usr/bin/python3 ]]; then
            system_python="/usr/bin/python3"
        else
            system_python="$(command -v python3 || true)"
        fi
        if [[ -z "${system_python}" ]]; then
            echo "[UI] System python3 was not found" >&2
            exit 1
        fi

        echo "[UI] Creating Python virtual environment: ${VENV_DIR}"
        if ! "${system_python}" -m venv --system-site-packages "${VENV_DIR}"; then
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
}

display_socket_path() {
    local display_name="$1"
    local display_number="${display_name#:}"
    display_number="${display_number%%.*}"
    printf '/tmp/.X11-unix/X%s\n' "${display_number}"
}

probe_x_display() {
    local display_name="$1"
    local xauthority_file="$2"

    DISPLAY="${display_name}" XAUTHORITY="${xauthority_file}" "${VENV_PYTHON}" - <<'PY' >/dev/null 2>&1
import ctypes
import os
import sys

try:
    libx11 = ctypes.CDLL("libX11.so.6")
    libx11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    libx11.XOpenDisplay.restype = ctypes.c_void_p
    libx11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    handle = libx11.XOpenDisplay(os.environ["DISPLAY"].encode("utf-8"))
    if not handle:
        raise SystemExit(1)
    libx11.XCloseDisplay(handle)
except Exception:
    raise SystemExit(1)
PY
}

select_display() {
    local deadline=$((SECONDS + DISPLAY_WAIT_SECONDS))
    local first_message=1

    while ((SECONDS <= deadline)); do
        local candidate
        for candidate in ${DISPLAY_CANDIDATES}; do
            local socket_path
            socket_path="$(display_socket_path "${candidate}")"

            if [[ -S "${socket_path}" && -r "${XAUTHORITY_PATH}" ]]; then
                if probe_x_display "${candidate}" "${XAUTHORITY_PATH}"; then
                    SELECTED_DISPLAY="${candidate}"
                    SELECTED_XAUTHORITY="${XAUTHORITY_PATH}"
                    return 0
                fi
            fi
        done

        if ((first_message)); then
            echo "[UI] Waiting for X display. Candidates: ${DISPLAY_CANDIDATES}; XAUTHORITY=${XAUTHORITY_PATH}"
            first_message=0
        fi
        sleep 1
    done

    echo "[UI] No usable X display found within ${DISPLAY_WAIT_SECONDS}s." >&2
    echo "[UI] Checked DISPLAY candidates: ${DISPLAY_CANDIDATES}" >&2
    echo "[UI] Checked XAUTHORITY: ${XAUTHORITY_PATH}" >&2
    echo "[UI] Tip: run 'ls -l /tmp/.X11-unix/' and verify the real desktop DISPLAY." >&2
    exit 1
}

start_ui() {
    ensure_project_files
    ensure_python_env
    select_display

    export DISPLAY="${SELECTED_DISPLAY}"
    export XAUTHORITY="${SELECTED_XAUTHORITY}"

    cd "${PROJECT_DIR}"

    local extra_args=()
    if [[ -n "${UI_EXTRA_ARGS}" ]]; then
        # shellcheck disable=SC2206
        extra_args=(${UI_EXTRA_ARGS})
    fi

    echo "[UI] Starting hardware UI on DISPLAY=${DISPLAY}, XAUTHORITY=${XAUTHORITY}"
    exec "${VENV_DIR}/bin/python" "${UI_ENTRY}" --backend hardware "${extra_args[@]}"
}

write_service_file() {
    cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=Photoelectric Current Measurement UI (1024x600 fullscreen)
After=display-manager.service systemd-user-sessions.service
Wants=display-manager.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_GROUP}
WorkingDirectory=${PROJECT_DIR}
Environment=HOME=${SERVICE_USER_HOME}
Environment=XDG_RUNTIME_DIR=/run/user/${SERVICE_USER_UID}
Environment=UICODE_PROJECT_DIR=${PROJECT_DIR}
Environment=UI_SERVICE_USER=${SERVICE_USER}
Environment=UI_SERVICE_GROUP=${SERVICE_GROUP}
Environment=UI_XAUTHORITY=${XAUTHORITY_PATH}
Environment="UI_DISPLAY_CANDIDATES=${DISPLAY_CANDIDATES}"
Environment=PYTHONUNBUFFERED=1
Environment=PYGAME_HIDE_SUPPORT_PROMPT=1
Environment=SDL_VIDEODRIVER=x11
ExecStart=/bin/bash ${PROJECT_DIR}/UI/run_hardware_ui.sh start
Restart=always
RestartSec=5
TimeoutStopSec=10

[Install]
WantedBy=graphical.target
EOF

    systemctl daemon-reload
    echo "[UI] Installed ${SERVICE_PATH}"
}

install_service() {
    require_root "install" "$@"
    write_service_file
}

enable_service() {
    require_root "enable" "$@"
    write_service_file
    systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1 || true
    systemctl enable "${SERVICE_NAME}"
    systemctl restart --no-block "${SERVICE_NAME}"
    echo "[UI] ${SERVICE_NAME} is enabled at boot. Start/restart job has been queued."
    echo "[UI] Check it with: systemctl status ${SERVICE_NAME} --no-pager -l"

    local default_target
    default_target="$(systemctl get-default 2>/dev/null || true)"
    if [[ "${default_target}" != "graphical.target" ]]; then
        echo "[UI] Current default target is '${default_target:-unknown}', not 'graphical.target'."
        echo "[UI] For touchscreen boot autostart, run once: sudo systemctl set-default graphical.target"
    fi
}

service_command() {
    local action="$1"
    shift || true
    require_root "${action}" "$@"
    systemctl "${action}" "$@" "${SERVICE_NAME}"
}

status_service() {
    if ! command -v systemctl >/dev/null 2>&1; then
        echo "[UI] systemctl is unavailable." >&2
        exit 1
    fi
    systemctl status "${SERVICE_NAME}" --no-pager
}

logs_service() {
    if ! command -v journalctl >/dev/null 2>&1; then
        echo "[UI] journalctl is unavailable." >&2
        exit 1
    fi
    journalctl -u "${SERVICE_NAME}" -f
}

verify_service() {
    echo "[UI] Service name: ${SERVICE_NAME}"
    echo "[UI] Service file: ${SERVICE_PATH}"
    echo "[UI] Project dir:  ${PROJECT_DIR}"
    echo "[UI] User:         ${SERVICE_USER}:${SERVICE_GROUP} uid=${SERVICE_USER_UID}"
    echo "[UI] XAUTHORITY:   ${XAUTHORITY_PATH}"
    echo "[UI] Candidates:   ${DISPLAY_CANDIDATES}"

    if command -v systemctl >/dev/null 2>&1; then
        echo "[UI] default target: $(systemctl get-default 2>/dev/null || echo unavailable)"
        echo "[UI] is-enabled:    $(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || true)"
        echo "[UI] is-active:     $(systemctl is-active "${SERVICE_NAME}" 2>/dev/null || true)"
        systemctl status "${SERVICE_NAME}" --no-pager -l || true
    fi

    echo "[UI] X sockets:"
    ls -l /tmp/.X11-unix/ 2>/dev/null || true

    if [[ -e "${XAUTHORITY_PATH}" ]]; then
        ls -l "${XAUTHORITY_PATH}" || true
    else
        echo "[UI] ${XAUTHORITY_PATH} does not exist"
    fi

    if command -v journalctl >/dev/null 2>&1; then
        echo "[UI] Recent logs:"
        journalctl -u "${SERVICE_NAME}" -n 80 --no-pager || true
    fi
}

uninstall_service() {
    require_root "uninstall"
    systemctl disable --now "${SERVICE_NAME}" >/dev/null 2>&1 || true
    rm -f -- "${SERVICE_PATH}"
    systemctl daemon-reload
    systemctl reset-failed "${SERVICE_NAME}" >/dev/null 2>&1 || true
    echo "[UI] Removed ${SERVICE_PATH}"
}

main() {
    local command_name="${1:-start}"
    shift || true

    case "${command_name}" in
        start|run)
            start_ui "$@"
            ;;
        install)
            install_service "$@"
            ;;
        enable|setup)
            enable_service "$@"
            ;;
        restart)
            service_command restart
            ;;
        stop)
            service_command stop
            ;;
        disable)
            service_command disable --now
            ;;
        status)
            status_service
            ;;
        logs)
            logs_service
            ;;
        verify|doctor)
            verify_service
            ;;
        uninstall|remove)
            uninstall_service "$@"
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            echo "[UI] Unknown command: ${command_name}" >&2
            usage >&2
            exit 2
            ;;
    esac
}

main "$@"
