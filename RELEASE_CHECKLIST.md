# Release checklist

## Completed locally

- [x] 49 unit and boundary tests
- [x] Python bytecode compilation
- [x] Ruff lint
- [x] Bash syntax and ShellCheck
- [x] systemd unit verification
- [x] udev rule verification
- [x] unprivileged scroll/pinch uinput preflight
- [x] dedicated keyboard-only ydotoold starts twice on its private `0600` socket
- [x] delayed boot-time uinput ACL is handled by bounded runtime retry
- [x] no personal paths, Bluetooth addresses, credentials, or world-writable input rules
- [x] retained MIT copyright and explicit third-party provenance
- [x] physical Magic Mouse 2 test of scroll, middle click, Back/Forward, pinch,
  GNOME workspace switching, and Overview
- [x] public GitHub CI

## Deferred clean-host portability checks

Version `v0.1.0` was released from the physically tested development machine.
These checks remain useful before claiming broader portability:

- [ ] Stop and disable the old local `magic-mouse-gestures.service` deployment.
- [ ] Install this repository through `./install.sh` as a normal desktop user.
- [ ] Reboot and verify service startup, one-finger scroll, Back/Forward, middle
  click, pinch, workspace left/right, and overview up.
- [ ] Run `./uninstall.sh`, reboot, and verify native pointer/buttons/scroll.
- [ ] Reinstall to verify idempotence and repeat the component checks.
- [x] Create `Salacfrantisek/magic-mouse-wayland-gestures` as a public repository,
  push `main`, enable private vulnerability reporting, and add topics such as
  `linux`, `wayland`, `magic-mouse`, `libinput`, and `uinput`.
- [x] Replace `unreleased` in `CHANGELOG.md` with the release date and tag
  `v0.1.0`.
