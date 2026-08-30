#!/usr/bin/env bash
# Standalone compatibility installer. Plugin installation is recommended.

set -euo pipefail

SKILL_NAME="banana"
INSTALL_VERSION="3.0.0"
INSTALL_ROOT="${HOME}/.claude/skills"
SKILL_DIR="${INSTALL_ROOT}/${SKILL_NAME}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/skills/${SKILL_NAME}"
MARKER_NAME=".banana-claude-install.json"

info() { printf '[INFO] %s\n' "$1"; }
error() { printf '[ERROR] %s\n' "$1" >&2; }

if [[ "${1:-}" == "--help" ]]; then
    printf '%s\n' \
        "Usage: ./install.sh [--uninstall]" \
        "" \
        "Plugin installation is recommended. This script installs only the" \
        "standalone /banana skill. It never stores or accepts API keys."
    exit 0
fi

ACTION="install"
if [[ "${1:-}" == "--uninstall" && $# -eq 1 ]]; then
    ACTION="uninstall"
elif [[ $# -gt 0 ]]; then
    error "Unknown option. Run ./install.sh --help for supported arguments."
    exit 2
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
    error "Python 3.11 or newer is required"
    exit 1
}

LIFECYCLE_HELPER="${SCRIPT_DIR}/tools/installer_lifecycle.py"
if [[ ! -f "${LIFECYCLE_HELPER}" ]]; then
    error "Installer lifecycle helper was not found."
    exit 1
fi

managed_skill_identity() {
    python3 "${LIFECYCLE_HELPER}" identity "$1" "${MARKER_NAME}"
}

directory_identity() {
    python3 "${LIFECYCLE_HELPER}" directory-identity "$1"
}

unique_destination() {
    python3 "${LIFECYCLE_HELPER}" unique-path "$1" "$2" "$3"
}

verify_completed_managed_move() {
    python3 "${LIFECYCLE_HELPER}" verify-move \
        "$1" "$2" "${MARKER_NAME}" "$3" "$4" "$5"
}

move_verified_managed_skill() {
    local moved_identity
    PENDING_MOVE_SOURCE="$1"
    PENDING_MOVE_DESTINATION="$2"
    PENDING_MOVE_IDENTITY="$3"
    PENDING_MOVE_SOURCE_PARENT_IDENTITY="$4"
    PENDING_MOVE_DESTINATION_PARENT_IDENTITY="$5"
    if ! python3 "${LIFECYCLE_HELPER}" move \
        "$1" "$2" "${MARKER_NAME}" "$3" "$4" "$5"; then
        if moved_identity="$(verify_completed_managed_move \
            "$1" "$2" "$3" "$4" "$5" 2>/dev/null)" && \
            [[ "${moved_identity}" == "$3" ]]; then
            error "The managed move helper was interrupted after publication; complete move receipt was reverified."
            PENDING_MOVE_SOURCE=""
            PENDING_MOVE_DESTINATION=""
            PENDING_MOVE_IDENTITY=""
            PENDING_MOVE_SOURCE_PARENT_IDENTITY=""
            PENDING_MOVE_DESTINATION_PARENT_IDENTITY=""
            return 0
        fi
        return 1
    fi
    if ! moved_identity="$(verify_completed_managed_move \
        "$1" "$2" "$3" "$4" "$5" 2>/dev/null)"; then
        return 1
    fi
    if [[ "${moved_identity}" != "$3" ]]; then
        return 1
    fi
    PENDING_MOVE_SOURCE=""
    PENDING_MOVE_DESTINATION=""
    PENDING_MOVE_IDENTITY=""
    PENDING_MOVE_SOURCE_PARENT_IDENTITY=""
    PENDING_MOVE_DESTINATION_PARENT_IDENTITY=""
    return 0
}

install_staged_skill() {
    python3 "${LIFECYCLE_HELPER}" install \
        "$1" "$2" "${MARKER_NAME}" "$3" "$4" "$5" "$6"
}

verify_installed_skill() {
    python3 "${LIFECYCLE_HELPER}" verify-install \
        "$1" "${MARKER_NAME}" "$2" "$3" "$4"
}

mkdir -p -- "${INSTALL_ROOT}"
if ! INSTALL_ROOT="$(python3 "${LIFECYCLE_HELPER}" canonical "${INSTALL_ROOT}")"; then
    error "The standalone install root could not be bound safely."
    exit 1
fi
SKILL_DIR="${INSTALL_ROOT}/${SKILL_NAME}"
if ! INSTALL_ROOT_IDENTITY="$(directory_identity "${INSTALL_ROOT}")"; then
    error "The standalone install root changed before it could be used."
    exit 1
fi
STAGE_SKILL=""
STAGE_SKILL_IDENTITY=""
STAGE_SNAPSHOT=""
STAGE_RESULT=""
STAGE_EXTRA=""
BACKUP_DIR=""
BACKUP_IDENTITY=""
PENDING_MOVE_SOURCE=""
PENDING_MOVE_DESTINATION=""
PENDING_MOVE_IDENTITY=""
PENDING_MOVE_SOURCE_PARENT_IDENTITY=""
PENDING_MOVE_DESTINATION_PARENT_IDENTITY=""
INSTALL_COMPLETE=0
cleanup() {
    exit_code=$?
    trap - EXIT HUP INT TERM
    set +e
    if [[ -n "${PENDING_MOVE_SOURCE}" ]] && \
        MOVED_IDENTITY="$(verify_completed_managed_move \
            "${PENDING_MOVE_SOURCE}" "${PENDING_MOVE_DESTINATION}" \
            "${PENDING_MOVE_IDENTITY}" \
            "${PENDING_MOVE_SOURCE_PARENT_IDENTITY}" \
            "${PENDING_MOVE_DESTINATION_PARENT_IDENTITY}" 2>/dev/null)" && \
        [[ "${MOVED_IDENTITY}" == "${PENDING_MOVE_IDENTITY}" ]]; then
        error "The managed move was interrupted after publication; complete move receipt was reverified."
    fi
    if [[ "${INSTALL_COMPLETE}" -eq 0 && -n "${STAGE_SKILL_IDENTITY}" && \
        -n "${STAGE_SNAPSHOT}" ]] && \
        RECOVERED_IDENTITY="$(verify_installed_skill \
            "${SKILL_DIR}" "${STAGE_SKILL_IDENTITY}" \
            "${INSTALL_ROOT_IDENTITY}" "${STAGE_SNAPSHOT}" 2>/dev/null)" && \
        [[ "${RECOVERED_IDENTITY}" == "${STAGE_SKILL_IDENTITY}" ]]; then
        error "The helper status was interrupted after publication; complete install receipt was reverified."
    fi
    if [[ "${INSTALL_COMPLETE}" -eq 0 && -n "${BACKUP_DIR}" ]] && \
        [[ -e "${BACKUP_DIR}" || -L "${BACKUP_DIR}" ]]; then
        error "Install failed; previous managed skill recovery candidate: ${BACKUP_DIR} (expected identity ${BACKUP_IDENTITY})."
        if [[ "${exit_code}" -ne 130 ]]; then
            exit_code=1
        fi
    fi
    if [[ "${exit_code}" -ne 0 && -n "${STAGE_SKILL}" ]] && \
        [[ -e "${STAGE_SKILL}" || -L "${STAGE_SKILL}" ]]; then
        error "Installer staging recovery candidate: ${STAGE_SKILL} (expected identity ${STAGE_SKILL_IDENTITY}, snapshot ${STAGE_SNAPSHOT})."
    fi
    exit "${exit_code}"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

if [[ "${ACTION}" == "uninstall" ]]; then
    if [[ ! -e "${SKILL_DIR}" && ! -L "${SKILL_DIR}" ]]; then
        info "Standalone skill is not installed at ${SKILL_DIR}"
        exit 0
    fi
    if ! SKILL_IDENTITY="$(managed_skill_identity "${SKILL_DIR}")"; then
        error "Refusing to remove a directory without a valid Banana ownership marker: ${SKILL_DIR}"
        exit 1
    fi
    if ! REMOVED_DIR="$(unique_destination \
        "${INSTALL_ROOT}" "${SKILL_NAME}.removed" \
        "${INSTALL_ROOT_IDENTITY}")"; then
        error "A unique uninstall recovery path could not be reserved safely."
        exit 1
    fi
    if ! move_verified_managed_skill \
        "${SKILL_DIR}" "${REMOVED_DIR}" "${SKILL_IDENTITY}" \
        "${INSTALL_ROOT_IDENTITY}" "${INSTALL_ROOT_IDENTITY}"; then
        if [[ -e "${REMOVED_DIR}" || -L "${REMOVED_DIR}" ]]; then
            error "Uninstall failed; inspect the recovery candidate at ${REMOVED_DIR} before retrying."
        else
            error "The managed skill changed during uninstall. No removal was accepted."
        fi
        exit 1
    fi
    info "Moved the standalone skill to ${REMOVED_DIR}"
    info "Local data under ${HOME}/.banana was preserved. Remove it manually if desired."
    exit 0
fi

if [[ ! -f "${SOURCE_DIR}/SKILL.md" ]]; then
    error "Skill source was not found at ${SOURCE_DIR}"
    exit 1
fi

if ! STAGE_SKILL="$(unique_destination \
    "${INSTALL_ROOT}" ".banana-stage" \
    "${INSTALL_ROOT_IDENTITY}")"; then
    error "A unique installer staging path could not be selected safely."
    exit 1
fi
if ! STAGE_RESULT="$(python3 "${LIFECYCLE_HELPER}" stage-source \
    "${SOURCE_DIR}" "${STAGE_SKILL}" "${MARKER_NAME}" \
    "${INSTALL_VERSION}" "${INSTALL_ROOT_IDENTITY}")"; then
    error "The installer could not build a descriptor-bound staging directory."
    exit 1
fi
read -r STAGE_SKILL_IDENTITY STAGE_SNAPSHOT STAGE_EXTRA <<< "${STAGE_RESULT}"
if [[ ! "${STAGE_SKILL_IDENTITY}" =~ ^[0-9]+:[0-9]+$ ]] || \
    [[ ! "${STAGE_SNAPSHOT}" =~ ^[0-9a-f]{64}$ ]] || \
    [[ -n "${STAGE_EXTRA}" ]]; then
    error "The installer staging receipt was invalid."
    exit 1
fi

if [[ -e "${SKILL_DIR}" || -L "${SKILL_DIR}" ]]; then
    if ! SKILL_IDENTITY="$(managed_skill_identity "${SKILL_DIR}")"; then
        error "Refusing to overwrite a skill without a valid Banana ownership marker at ${SKILL_DIR}"
        exit 1
    fi
    if ! BACKUP_DIR="$(unique_destination \
        "${INSTALL_ROOT}" "${SKILL_NAME}.backup" \
        "${INSTALL_ROOT_IDENTITY}")"; then
        error "A unique backup path could not be reserved safely."
        exit 1
    fi
    BACKUP_IDENTITY="${SKILL_IDENTITY}"
    if ! move_verified_managed_skill \
        "${SKILL_DIR}" "${BACKUP_DIR}" "${BACKUP_IDENTITY}" \
        "${INSTALL_ROOT_IDENTITY}" "${INSTALL_ROOT_IDENTITY}"; then
        error "The managed skill changed before backup. No replacement was accepted."
        exit 1
    fi
    info "Previous managed install backed up to ${BACKUP_DIR}"
fi

if ! INSTALLED_IDENTITY="$(install_staged_skill \
    "${STAGE_SKILL}" "${SKILL_DIR}" "${STAGE_SKILL_IDENTITY}" \
    "${INSTALL_ROOT_IDENTITY}" "${INSTALL_ROOT_IDENTITY}" \
    "${STAGE_SNAPSHOT}")"; then
    if RECOVERED_IDENTITY="$(verify_installed_skill \
        "${SKILL_DIR}" "${STAGE_SKILL_IDENTITY}" \
        "${INSTALL_ROOT_IDENTITY}" "${STAGE_SNAPSHOT}")"; then
        INSTALLED_IDENTITY="${RECOVERED_IDENTITY}"
        error "The helper status was interrupted after publication; the complete install receipt was reverified."
    else
        error "The staged skill transaction did not complete successfully."
        if [[ -e "${SKILL_DIR}" || -L "${SKILL_DIR}" ]]; then
            error "Unresolved install target retained at ${SKILL_DIR} (expected staged identity ${STAGE_SKILL_IDENTITY}, snapshot ${STAGE_SNAPSHOT})."
        fi
        exit 1
    fi
fi
if ! FINAL_IDENTITY="$(verify_installed_skill \
    "${SKILL_DIR}" "${STAGE_SKILL_IDENTITY}" \
    "${INSTALL_ROOT_IDENTITY}" "${STAGE_SNAPSHOT}")" || \
    [[ "${FINAL_IDENTITY}" != "${INSTALLED_IDENTITY}" ]]; then
    error "The install target or complete receipt changed before final acceptance. Inspect retained directories before retrying."
    exit 1
fi
INSTALL_COMPLETE=1

info "Installed the standalone /banana skill at ${SKILL_DIR}"
info "Set GEMINI_API_KEY in the launching environment before paid execution."
info "For secure key storage and the bundled MCP tools, use the Claude Code plugin install instead."
