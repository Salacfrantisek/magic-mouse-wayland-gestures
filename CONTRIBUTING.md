# Contributing

Bug reports should include the sanitized `HID_ID`, Linux distribution, kernel,
desktop session, and libinput version. Do not include Bluetooth addresses,
usernames, full raw journals, or other machine-specific identifiers.

Before submitting a change, run:

```bash
python3 -m pytest -q
python3 -m py_compile magic_mouse_gestures.py
ruff check .
bash -n install.sh uninstall.sh
```

Changes to virtual-device capabilities or gesture arbitration must add a test
and update the relevant invariant in `SPEC.md`. New hardware IDs require
physical evidence and must not silently broaden existing udev matches.
