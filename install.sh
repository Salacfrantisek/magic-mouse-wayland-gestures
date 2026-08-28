#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT="magic-mouse-wayland-gestures"
INSTALL_DIR="/opt/$PROJECT"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_NAME="$PROJECT.service"
YDOTOOL_SERVICE_NAME="$PROJECT-ydotool.service"
UDEV_FILE="/etc/udev/rules.d/70-$PROJECT.rules"
LEGACY_UDEV_FILE="/etc/udev/rules.d/99-$PROJECT.rules"
MODPROBE_FILE="/etc/modprobe.d/99-$PROJECT.conf"
MODULES_LOAD_FILE="/etc/modules-load.d/$PROJECT.conf"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

KERNEL_CHANGED=false
MODPROBE_TOUCHED=false
MOUSE_MAC=""
PREVIOUS_MODPROBE=""
ORIGINAL_SCROLL=""
ORIGINAL_ACCEL=""
ORIGINAL_SPEED=""
ORIGINAL_MIDDLE=""

cleanup_temp() {
    if [[ -n "$PREVIOUS_MODPROBE" && -f "$PREVIOUS_MODPROBE" ]]; then
        unlink "$PREVIOUS_MODPROBE"
        rmdir "$(dirname "$PREVIOUS_MODPROBE")" 2>/dev/null || true
    fi
}

write_parameter() {
    local name="$1"
    local value="$2"
    printf '%s\n' "$value" | sudo tee "/sys/module/hid_magicmouse/parameters/$name" >/dev/null
}

rollback() {
    local status="${1:-1}"
    trap - ERR INT TERM
    set +e
    printf '\n%bInstallation failed; restoring native input settings.%b\n' "$YELLOW" "$NC" >&2

    systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1
    systemctl --user stop "$YDOTOOL_SERVICE_NAME" >/dev/null 2>&1

    if [[ "$KERNEL_CHANGED" == true ]]; then
        [[ -n "$ORIGINAL_SCROLL" ]] && write_parameter emulate_scroll_wheel "$ORIGINAL_SCROLL"
        [[ -n "$ORIGINAL_ACCEL" ]] && write_parameter scroll_acceleration "$ORIGINAL_ACCEL"
        [[ -n "$ORIGINAL_SPEED" ]] && write_parameter scroll_speed "$ORIGINAL_SPEED"
        [[ -n "$ORIGINAL_MIDDLE" ]] && write_parameter emulate_3button "$ORIGINAL_MIDDLE"
    fi

    if [[ "$MODPROBE_TOUCHED" == true ]]; then
        if [[ -n "$PREVIOUS_MODPROBE" && -f "$PREVIOUS_MODPROBE" ]]; then
            sudo install -m 0644 "$PREVIOUS_MODPROBE" "$MODPROBE_FILE"
        else
            sudo rm -f "$MODPROBE_FILE"
        fi
    fi

    if [[ -n "$MOUSE_MAC" ]]; then
        bluetoothctl connect "$MOUSE_MAC" >/dev/null 2>&1 || true
    fi
    cleanup_temp
    exit "$status"
}

trap 'rollback $?' ERR
trap 'rollback 130' INT TERM

if [[ $EUID -eq 0 ]]; then
    printf '%bDo not run this installer with sudo.%b\n' "$RED" "$NC" >&2
    echo "Run it as your normal desktop user: ./install.sh" >&2
    exit 1
fi

echo "Magic Mouse Wayland Gestures installer"
echo

for command in python3 bluetoothctl systemctl udevadm ydotool ydotoold; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf '%bMissing dependency: %s%b\n' "$RED" "$command" "$NC" >&2
        exit 1
    fi
done
if ! ydotoold --help 2>&1 | grep -q -- '--socket-path' ||
        ! ydotoold --help 2>&1 | grep -q -- '--mouse-off'; then
    printf '%bInstalled ydotoold lacks --socket-path or --mouse-off support.%b\n' "$RED" "$NC" >&2
    exit 1
fi
if ! python3 -c 'import evdev' >/dev/null 2>&1; then
    printf '%bMissing Python evdev module.%b\n' "$RED" "$NC" >&2
    echo "Ubuntu/Debian: sudo apt install python3-evdev" >&2
    exit 1
fi

echo "Detecting a supported Magic Mouse..."
if ! python3 "$SCRIPT_DIR/magic_mouse_gestures.py" --detect-device; then
    printf '%bNo supported mouse is currently connected; installing support for both known models.%b\n' "$YELLOW" "$NC"
fi

sudo -v

# Install project-owned access rules first. No kernel behavior changes yet.
sudo install -m 0644 "$SCRIPT_DIR/udev/70-$PROJECT.rules" "$UDEV_FILE"
sudo rm -f "$LEGACY_UDEV_FILE"
sudo install -m 0644 "$SCRIPT_DIR/modules-load/$PROJECT.conf" "$MODULES_LOAD_FILE"
sudo modprobe uinput
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change --subsystem-match=misc --sysname-match=uinput || true
sudo udevadm trigger --action=change --subsystem-match=hidraw || true
sudo udevadm settle

echo "Checking isolated scroll and gesture devices..."
python3 "$SCRIPT_DIR/magic_mouse_gestures.py" --check-uinput

# Install runtime and user units only after unprivileged uinput succeeds.
sudo install -d -m 0755 "$INSTALL_DIR"
sudo install -m 0755 "$SCRIPT_DIR/magic_mouse_gestures.py" "$INSTALL_DIR/magic_mouse_gestures.py"
install -d -m 0755 "$USER_SERVICE_DIR"
install -m 0644 "$SCRIPT_DIR/systemd/$SERVICE_NAME" "$USER_SERVICE_DIR/$SERVICE_NAME"
install -m 0644 "$SCRIPT_DIR/systemd/$YDOTOOL_SERVICE_NAME" "$USER_SERVICE_DIR/$YDOTOOL_SERVICE_NAME"

systemctl --user daemon-reload

# Save the original live state and project config for error rollback.
if [[ -d /sys/module/hid_magicmouse/parameters ]]; then
    for parameter in emulate_scroll_wheel scroll_acceleration scroll_speed emulate_3button; do
        if [[ ! -e "/sys/module/hid_magicmouse/parameters/$parameter" ]]; then
            printf '%bLoaded hid_magicmouse lacks parameter %s.%b\n' "$RED" "$parameter" "$NC" >&2
            exit 1
        fi
    done
    ORIGINAL_SCROLL="$(</sys/module/hid_magicmouse/parameters/emulate_scroll_wheel)"
    ORIGINAL_ACCEL="$(</sys/module/hid_magicmouse/parameters/scroll_acceleration)"
    ORIGINAL_SPEED="$(</sys/module/hid_magicmouse/parameters/scroll_speed)"
    ORIGINAL_MIDDLE="$(</sys/module/hid_magicmouse/parameters/emulate_3button)"
fi

if sudo test -f "$MODPROBE_FILE"; then
    rollback_dir="$(mktemp -d)"
    PREVIOUS_MODPROBE="$rollback_dir/modprobe.conf"
    sudo cat "$MODPROBE_FILE" | tee "$PREVIOUS_MODPROBE" >/dev/null
fi
MODPROBE_TOUCHED=true
sudo install -m 0644 "$SCRIPT_DIR/modprobe/99-$PROJECT.conf" "$MODPROBE_FILE"

mapfile -t mouse_candidates < <(
    bluetoothctl devices Paired 2>/dev/null |
        awk 'BEGIN { IGNORECASE=1 } /Magic Mouse/ { print $2 }'
)
if [[ ${#mouse_candidates[@]} -eq 1 ]]; then
    MOUSE_MAC="${mouse_candidates[0]}"
elif [[ ${#mouse_candidates[@]} -gt 1 ]]; then
    printf '%bMultiple paired Magic Mouse devices found; automatic reprobe skipped.%b\n' "$YELLOW" "$NC"
else
    printf '%bNo paired device named Magic Mouse found; automatic reprobe skipped.%b\n' "$YELLOW" "$NC"
fi

# From here on every failure restores the original live kernel settings.
if [[ -d /sys/module/hid_magicmouse/parameters ]]; then
    KERNEL_CHANGED=true
    write_parameter emulate_3button 1
fi

if [[ -n "$MOUSE_MAC" ]]; then
    echo "Reprobing the paired Magic Mouse..."
    bluetoothctl disconnect "$MOUSE_MAC" >/dev/null 2>&1 || true
    sleep 2
    bluetoothctl connect "$MOUSE_MAC" >/dev/null
    sleep 3
    python3 "$SCRIPT_DIR/magic_mouse_gestures.py" --check-middle-click
else
    echo "Power-cycle the Magic Mouse after installation to activate middle click."
fi

if [[ -d /sys/module/hid_magicmouse/parameters ]]; then
    write_parameter scroll_acceleration 0
    write_parameter scroll_speed 22
    write_parameter emulate_scroll_wheel 0
fi

systemctl --user reenable "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME"
sleep 2
systemctl --user is-active --quiet "$SERVICE_NAME"

trap - ERR INT TERM
cleanup_temp

printf '%bInstallation complete.%b\n' "$GREEN" "$NC"
echo "Status: systemctl --user status $SERVICE_NAME"
echo "Logs:   journalctl --user -u $SERVICE_NAME -f"
echo "Uninstall: ./uninstall.sh"
