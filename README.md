# Magic Mouse Wayland Gestures

Linux/Wayland integration for Apple Magic Mouse 2 that adds one-finger
scrolling, two-finger Back/Forward, kernel-native middle click, smooth
touchpad-style pinch zoom, and GNOME three-finger navigation.

> [!IMPORTANT]
> This is an experimental desktop integration, not a kernel driver. The first
> public release supports only the Bluetooth Magic Mouse 2 identified as
> `004C:0269`. The `support/usb-c-0323` branch adds an unverified candidate for
> the USB-C revision `004C:0323`; it is not supported until physical acceptance
> is complete. Read the tested-platform and security notes before installing.

## Features

| Input | Result |
|---|---|
| One-finger vertical or horizontal movement | Sticky-axis high-resolution scroll |
| Two-finger horizontal swipe | Back / Forward (`Alt+Left` / `Alt+Right`) |
| Two-finger spread or pinch | Native libinput/Wayland pinch gesture |
| Three-finger swipe left or right | Switch GNOME workspace |
| Three-finger swipe up | Open GNOME overview |
| Physical click with one finger in the center zone | Kernel-native middle click |
| Pointer movement and left/right click | Unchanged kernel behavior |

Pinch and navigation share a locked gesture arbiter. Once a two-finger contact
sequence becomes a pinch it cannot navigate, and once it becomes a swipe it
cannot turn into a pinch until both contacts lift.

## Exact tested setup

This is the configuration physically tested on 12 August 2026:

| Component | Tested value |
|---|---|
| Mouse | Apple Magic Mouse 2, Bluetooth/Lightning generation |
| HID identity | bus `0005`, vendor `004C`, product `0269`, device version `0192` |
| Connection | Bluetooth |
| Operating system | Ubuntu 26.04 LTS |
| Desktop | GNOME Shell 50.1 |
| Session | Wayland |
| Kernel | `7.0.0-28-generic` with the in-tree `hid_magicmouse` driver |
| libinput | 1.31.1 |
| Python | 3.14.4 with `python3-evdev` |

The tested mouse is product `0269`. It is not the newer USB-C revision, which
uses a different product ID. Color and printed model number do not affect the
HID match and were not used to identify the device.

The physical test covered pointer and left/right click, one-finger scrolling,
center-zone middle click, two-finger Back/Forward, pinch zoom, GNOME workspace
swipes, and the three-finger upward Overview gesture.

Unit tests cover the gesture state machines and virtual-device capability
boundaries. Other distributions, desktop environments, kernel versions, and
newer USB-C Magic Mouse revisions are not yet claimed as supported.

## What gets changed

The mouse firmware is not modified. No out-of-tree or DKMS mouse driver is
installed. The project changes only these host-side pieces:

| Layer | Change |
|---|---|
| Kernel module settings | `emulate_3button=1`, `emulate_scroll_wheel=0`, `scroll_acceleration=0`, `scroll_speed=22` |
| Physical device | Still handled by in-tree `hid_magicmouse` for pointer movement and all physical buttons |
| Touch reports | Read from the exact allowlist `004C:0269` and experimental `004C:0323` without grabbing the device |
| One finger | Emitted through a scroll-only uinput device |
| Two-finger pinch | Emitted as two contacts on a gesture-only virtual touchpad |
| Three-finger swipe | Emitted as three translating contacts; GNOME decides workspace or Overview behavior |
| Back/Forward | Emitted as keyboard-only `Alt+Left` / `Alt+Right` through a private `ydotoold --mouse-off` socket |

The two virtual devices deliberately have no mouse buttons or pointer-motion
axes. If the userspace service stops, the physical pointer and clicks remain
kernel-controlled; only the added scrolling and gestures disappear.

## Why this design

The physical mouse remains owned by the in-tree Linux `hid_magicmouse` driver.
This project reads raw touch reports without grabbing the device and exposes
only the missing outputs:

```text
Magic Mouse 2
├── kernel hid_magicmouse → pointer + physical buttons + middle click
└── read-only hidraw touch reports
    ├── one finger → scroll-only uinput device
    ├── two-finger pinch → gesture-only multitouch uinput → libinput/Wayland
    ├── three-finger swipe → same gesture-only uinput → GNOME
    └── two-finger swipe → dedicated keyboard-only ydotoold → Alt+Left/Right
```

The scroll device has no pointer axes or buttons. The gesture device has no
relative axes or mouse buttons. A project-specific `ydotoold` runs with
`--mouse-off` and its own socket, so it cannot create a second virtual pointer
or modify another application's ydotool service.

The gesture adapter emits synthetic touchpad contacts. Two contacts change
distance for pinch. Three contacts keep their distance and move together for a
swipe. Applications and GNOME receive normal libinput gestures while the real
mouse continues to provide the pointer.

Apple Magic Trackpads normally appear as real touchpads in Linux and already
provide libinput gestures. This project is aimed at Magic Mouse 2. Do not add a
Trackpad or another Magic Mouse product ID without physical testing in a
separate branch.

## Requirements

- Linux with the in-tree `hid_magicmouse` module and its `emulate_3button`
  parameter
- A systemd user session and BlueZ (`bluetoothctl`)
- Python 3.8 or newer
- Python `evdev`
- `ydotool` / `ydotoold` with `--mouse-off` support
- `/dev/uinput`

Ubuntu/Debian dependencies:

```bash
sudo apt install python3 python3-evdev ydotool bluez
```

## Install

Do not run the installer itself with `sudo`; it requests privilege only for
project-owned system files and kernel parameters.

```bash
git clone https://github.com/Salacfrantisek/magic-mouse-wayland-gestures.git
cd magic-mouse-wayland-gestures
./install.sh
```

The installer is fail-safe around scroll ownership:

1. installs exact udev access rules and loads `uinput`;
2. proves the unprivileged user can create both limited virtual devices;
3. installs the runtime and user services;
4. records the original live kernel parameters;
5. enables middle click, reprobes only one unambiguous paired Magic Mouse;
6. disables kernel scroll only after preflight succeeds;
7. restores native live and persistent scroll settings if a later step fails.

The service is part of `graphical-session.target`, so a lingering user manager
cannot start it before the local desktop session exists. If logind grants
`/dev/uinput` access a few seconds late inside that session, the service waits
with bounded backoff instead of crashing; the dedicated ydotoold also retries
without a systemd start-rate limit.

If the paired device name does not contain `Magic Mouse`, automatic Bluetooth
reprobe is skipped. Power-cycle the mouse once after installation; the script
never falls back to disconnecting an arbitrary mouse.

### Files installed

```text
/opt/magic-mouse-wayland-gestures/magic_mouse_gestures.py
/etc/udev/rules.d/70-magic-mouse-wayland-gestures.rules
/etc/modprobe.d/99-magic-mouse-wayland-gestures.conf
/etc/modules-load.d/magic-mouse-wayland-gestures.conf
~/.config/systemd/user/magic-mouse-wayland-gestures.service
~/.config/systemd/user/magic-mouse-wayland-gestures-ydotool.service
```

The uniquely named modprobe file intentionally sorts late. The installer does
not overwrite a generic `/etc/modprobe.d/hid-magicmouse.conf`, but conflicting
third-party options should be removed or reconciled before installation.

## Verify

```bash
systemctl --user status magic-mouse-wayland-gestures.service
journalctl --user -u magic-mouse-wayland-gestures.service --no-pager
python3 /opt/magic-mouse-wayland-gestures/magic_mouse_gestures.py --check-uinput
python3 /opt/magic-mouse-wayland-gestures/magic_mouse_gestures.py --check-middle-click
libinput list-devices
```

The libinput listing should show `Magic Mouse Gesture Touchpad` with
`Capabilities: pointer gesture`.

## Configuration

Defaults are conservative and match the tested mouse:

| Environment variable | Default | Meaning |
|---|---:|---|
| `SCROLL_SPEED` | `22` | Scroll conversion speed (`0`–`63`) |
| `SCROLL_LOCK_RATIO` | `1.5` | Dominance required to select an axis |
| `SCROLL_LOCK_TIMEOUT` | `0.25` | Inactivity before axis unlock, seconds |
| `SCROLL_ACCEL_MAX` | `2.3` | Maximum repeated-stroke acceleration |
| `PINCH_THRESHOLD_MM` | `2.0` | Distance change before pinch locks |
| `PINCH_DOMINANCE` | `1.3` | Distance change versus centroid travel |
| `DEBUG` | unset | Set to `1` for verbose touch logging |

Use a systemd drop-in rather than editing the installed unit:

```bash
systemctl --user edit magic-mouse-wayland-gestures.service
```

Example:

```ini
[Service]
Environment=PINCH_THRESHOLD_MM=2.5
Environment=SCROLL_SPEED=20
```

Then run:

```bash
systemctl --user daemon-reload
systemctl --user restart magic-mouse-wayland-gestures.service
```

## Security model

Access is limited to the active local desktop session using udev `uaccess`.
The Magic Mouse hidraw node and `/dev/uinput` are not made world-writable and
the user is not added to the broad `input` group.

Any process that can write `/dev/uinput` can synthesize input events. This
capability is necessary for scroll and pinch output, so install only reviewed
code. The service runs unprivileged with systemd filesystem, privilege,
kernel-tunable, and executable-memory hardening.

## Uninstall and rollback

```bash
./uninstall.sh
```

Uninstall restores live native kernel scrolling and the default middle-click
setting, and removes only project-owned paths and services. It never changes
the shared `ydotool.service`. No kernel module is unloaded and pointer/left/
right-click behavior is never replaced.

If you need immediate manual scroll recovery:

```bash
echo 1 | sudo tee /sys/module/hid_magicmouse/parameters/emulate_scroll_wheel
systemctl --user stop magic-mouse-wayland-gestures.service
```

## Development

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m py_compile magic_mouse_gestures.py
ruff check .
bash -n install.sh uninstall.sh
```

The architecture invariants and regression history are documented in
[`SPEC.md`](SPEC.md). Further clean-host portability checks are tracked in
[`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md).

## Credits and provenance

This repository is a substantial derivative of Breno Perucchi's MIT-licensed
[`magic-mouse-gestures`](https://github.com/brenoperucchi/magic-mouse-gestures).
Its copyright notice is retained in [`LICENSE`](LICENSE).

Research into middle-click behavior and Magic Mouse 2 report layout also used
Ricardo Rodrigues' maintenance-mode
[`magicmouse-hid`](https://github.com/RicardoEPRodrigues/magicmouse-hid) and the
in-tree Linux `hid_magicmouse` implementation as technical references. No
kernel-driver source from those projects is included here.

See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the precise boundary
between derived code, external reference material, and new work.

## License

MIT. See [`LICENSE`](LICENSE).
