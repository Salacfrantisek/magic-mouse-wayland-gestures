#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT="magic-mouse-wayland-gestures"
INSTALL_DIR="/opt/$PROJECT"
USER_SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_NAME="$PROJECT.service"
YDOTOOL_SERVICE_NAME="$PROJECT-ydotool.service"
UDEV_FILE="/etc/udev/rules.d/99-$PROJECT.rules"
MODPROBE_FILE="/etc/modprobe.d/99-$PROJECT.conf"
MODULES_LOAD_FILE="/etc/modules-load.d/$PROJECT.conf"

if [[ $EUID -eq 0 ]]; then
    echo "Do not run this uninstaller with sudo." >&2
    echo "Run it as your normal desktop user: ./uninstall.sh" >&2
    exit 1
fi

sudo -v

systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true

# Restore the kernel defaults changed by this project before removing files.
if [[ -e /sys/module/hid_magicmouse/parameters/emulate_scroll_wheel ]]; then
    printf '1\n' | sudo tee /sys/module/hid_magicmouse/parameters/emulate_scroll_wheel >/dev/null
fi
if [[ -e /sys/module/hid_magicmouse/parameters/scroll_acceleration ]]; then
    printf '1\n' | sudo tee /sys/module/hid_magicmouse/parameters/scroll_acceleration >/dev/null
fi
if [[ -e /sys/module/hid_magicmouse/parameters/emulate_3button ]]; then
    printf '0\n' | sudo tee /sys/module/hid_magicmouse/parameters/emulate_3button >/dev/null
fi

systemctl --user stop "$YDOTOOL_SERVICE_NAME" >/dev/null 2>&1 || true
unlink "$USER_SERVICE_DIR/$SERVICE_NAME" 2>/dev/null || true
unlink "$USER_SERVICE_DIR/$YDOTOOL_SERVICE_NAME" 2>/dev/null || true
systemctl --user daemon-reload

sudo rm -f "$INSTALL_DIR/magic_mouse_gestures.py"
sudo rmdir "$INSTALL_DIR" 2>/dev/null || true
sudo rm -f "$UDEV_FILE" "$MODPROBE_FILE" "$MODULES_LOAD_FILE"
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change --subsystem-match=misc --sysname-match=uinput || true
sudo udevadm trigger --action=change --subsystem-match=hidraw || true

echo "Uninstall complete. Native kernel scrolling and default click behavior are restored."
