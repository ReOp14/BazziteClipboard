#!/usr/bin/env bash
set -euo pipefail

APP_NAME="bazzite-clipboard"
DISPLAY_NAME="Bazzite Clipboard"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
BIN_PATH="${BIN_DIR}/${APP_NAME}"
AUTOSTART_DIR="${HOME}/.config/autostart"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
AUTOSTART_DESKTOP="${AUTOSTART_DIR}/${APP_NAME}.desktop"
APP_DESKTOP="${APPLICATIONS_DIR}/${APP_NAME}.desktop"
TOGGLE_DESKTOP="${APPLICATIONS_DIR}/${APP_NAME}-toggle.desktop"
PYTHON="/usr/bin/python3"

usage() {
    cat <<EOF
Usage: $0 [--uninstall]

Install ${DISPLAY_NAME} for this user:
  - launcher at ${BIN_PATH}
  - autostart on login
  - Ctrl+\` global shortcut (Plasma)
  - start the daemon now

Use --uninstall to remove the launcher, autostart, and shortcut.
Clipboard history in ~/.local/share/bazzite-clipboard is kept unless you
also pass --purge.
EOF
}

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Missing required command: $1" >&2
        exit 1
    }
}

write_launcher() {
    mkdir -p "${BIN_DIR}"
    cat > "${BIN_PATH}" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${REPO_DIR}/src\${PYTHONPATH:+:\$PYTHONPATH}"
exec ${PYTHON} -m bazzite_clipboard "\$@"
EOF
    chmod +x "${BIN_PATH}"
}

write_desktops() {
    mkdir -p "${AUTOSTART_DIR}" "${APPLICATIONS_DIR}"

    cat > "${APP_DESKTOP}" <<EOF
[Desktop Entry]
Type=Application
Name=${DISPLAY_NAME}
Comment=Clipboard history with image previews
Exec=${BIN_PATH} --toggle
Icon=edit-paste
Terminal=false
Categories=Utility;Qt;
StartupNotify=false
X-KDE-StartupNotify=false
EOF

    cat > "${AUTOSTART_DESKTOP}" <<EOF
[Desktop Entry]
Type=Application
Name=${DISPLAY_NAME}
Comment=Clipboard history daemon
Exec=${BIN_PATH}
Icon=edit-paste
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
X-KDE-autostart-phase=2
StartupNotify=false
EOF

    cat > "${TOGGLE_DESKTOP}" <<EOF
[Desktop Entry]
Type=Application
Name=Toggle ${DISPLAY_NAME}
Comment=Show clipboard history at the cursor
Exec=${BIN_PATH} --toggle
Icon=edit-paste
Terminal=false
NoDisplay=true
StartupNotify=false
X-KDE-GlobalAccel-CommandShortcut=true
EOF
}

register_shortcut() {
    if ! command -v kwriteconfig6 >/dev/null 2>&1; then
        echo "kwriteconfig6 not found; skip global shortcut registration." >&2
        return
    fi

    kwriteconfig6 --file kglobalshortcutsrc \
        --group "${APP_NAME}-toggle.desktop" \
        --key "_k_friendly_name" "${DISPLAY_NAME}"
    kwriteconfig6 --file kglobalshortcutsrc \
        --group "${APP_NAME}-toggle.desktop" \
        --key "_launch" "Ctrl+\`,none,Toggle ${DISPLAY_NAME}"

    if command -v kbuildsycoca6 >/dev/null 2>&1; then
        kbuildsycoca6 >/dev/null 2>&1 || true
    fi
    if command -v qdbus >/dev/null 2>&1; then
        qdbus org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.reloadConfig >/dev/null 2>&1 || true
    fi
    if command -v gdbus >/dev/null 2>&1; then
        gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
            --method org.kde.KGlobalAccel.reloadConfig >/dev/null 2>&1 || true
    fi
}

start_daemon() {
    if ${PYTHON} - <<'PY' >/dev/null 2>&1
import dbus, sys
sys.exit(0 if dbus.SessionBus().name_has_owner("org.bazzite.Clipboard") else 1)
PY
    then
        echo "${DISPLAY_NAME} is already running."
        return
    fi
    nohup "${BIN_PATH}" >/dev/null 2>&1 &
    disown || true
    echo "Started ${DISPLAY_NAME}."
}

uninstall() {
    if command -v qdbus >/dev/null 2>&1; then
        qdbus org.bazzite.Clipboard /org/bazzite/Clipboard org.bazzite.Clipboard.Toggle >/dev/null 2>&1 || true
    fi
    pkill -f "python3 -m bazzite_clipboard" >/dev/null 2>&1 || true
    rm -f "${BIN_PATH}" "${AUTOSTART_DESKTOP}" "${APP_DESKTOP}" "${TOGGLE_DESKTOP}"
    if command -v kwriteconfig6 >/dev/null 2>&1; then
        kwriteconfig6 --file kglobalshortcutsrc \
            --group "${APP_NAME}-toggle.desktop" --key "_launch" --delete >/dev/null 2>&1 || true
        kwriteconfig6 --file kglobalshortcutsrc \
            --group "${APP_NAME}-toggle.desktop" --key "_k_friendly_name" --delete >/dev/null 2>&1 || true
    fi
    echo "Removed launcher, autostart, and shortcut."
    if [[ "${1:-}" == "--purge" ]]; then
        rm -rf "${HOME}/.local/share/bazzite-clipboard" "${HOME}/.local/state/bazzite-clipboard"
        echo "Removed stored clipboard history."
    fi
}

main() {
    case "${1:-}" in
        -h|--help)
            usage
            ;;
        --uninstall)
            uninstall "${2:-}"
            ;;
        "")
            need_cmd "${PYTHON}"
            need_cmd wl-paste
            need_cmd wl-copy
            write_launcher
            write_desktops
            register_shortcut
            start_daemon
            cat <<EOF

Installed ${DISPLAY_NAME}.

  Launcher:   ${BIN_PATH}
  Autostart:  ${AUTOSTART_DESKTOP}
  Shortcut:   Ctrl+\`  (Toggle ${DISPLAY_NAME})
  History:    ~/.local/share/bazzite-clipboard

If Ctrl+\` does nothing, add it in System Settings → Keyboard → Shortcuts
→ Add New → Command or Script, command: ${BIN_PATH} --toggle
Use that full path; KDE does not expand ~.

Cursor/VS Code also uses Ctrl+\` for the terminal; the Plasma global
shortcut takes precedence while it is assigned.
EOF
            ;;
        *)
            usage >&2
            exit 1
            ;;
    esac
}

main "$@"
