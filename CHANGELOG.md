# Changelog

## Unreleased

- Order the Magic Mouse udev rule before systemd seat ACL processing.
- Start the gesture pipeline only as part of the local graphical session.

## 0.1.0 - 2026-08-12

- Preserve kernel-native pointer movement and physical buttons.
- Add one-finger high-resolution scroll with sticky axis locking.
- Add mutually exclusive two-finger Back/Forward and native Wayland pinch.
- Add native three-finger GNOME workspace and overview gestures.
- Enable kernel-native center-zone middle click.
- Add isolated uinput capability boundaries and regression tests.
- Add transactional installation, least-privilege udev rules, safe uninstall,
  service hardening, and explicit upstream provenance.
- Tolerate delayed boot-time uinput ACLs without traceback or service restart.
