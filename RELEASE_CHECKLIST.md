# Release checklist

## Completed locally

- [x] 42 unit and boundary tests
- [x] Python bytecode compilation
- [x] Ruff lint
- [x] Bash syntax and ShellCheck
- [x] systemd unit verification
- [x] udev rule verification
- [x] unprivileged scroll/pinch uinput preflight
- [x] dedicated keyboard-only ydotoold starts twice on its private `0600` socket
- [x] no personal paths, Bluetooth addresses, credentials, or world-writable input rules
- [x] retained MIT copyright and explicit third-party provenance

## Required before the first public release

- [ ] Stop and disable the old local `magic-mouse-gestures.service` deployment.
- [ ] Install this repository through `./install.sh` as a normal desktop user.
- [ ] Reboot and verify service startup, one-finger scroll, Back/Forward, middle
  click, and pinch in at least a browser and one non-browser application.
- [ ] Run `./uninstall.sh`, reboot, and verify native pointer/buttons/scroll.
- [ ] Reinstall to verify idempotence and repeat the component checks.
- [ ] Create `Salacfrantisek/magic-mouse-wayland-gestures` as a public repository,
  push `main`, enable private vulnerability reporting, and add topics such as
  `linux`, `wayland`, `magic-mouse`, `libinput`, and `uinput`.
- [ ] Replace `unreleased` in `CHANGELOG.md` with the release date and tag
  `v0.1.0` only after the clean lifecycle test passes.
