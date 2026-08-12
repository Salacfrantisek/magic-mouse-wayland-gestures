§G

Publishable Magic Mouse 2 Wayland integration: kernel pointer/buttons/middle click, userspace sticky scroll, Back/Forward, and native pinch zoom.

§C

- One existing Python service/process only.
- Physical pointer/buttons and middle click stay kernel-native.
- No evdev grab, pointer/button re-emission, scroll subprocess, polling loop, or ydotool scroll.
- Existing raw HID reader supplies touch samples; separate scroll-only and pinch-only uinput devices supply outputs.
- One finger scrolls. Two fingers lock to either native pinch or browser Back/Forward for the full contact sequence.
- Defaults: speed 22, dominance ratio 1.5, unlock after 250 ms inactivity, acceleration enabled with about 2.3x maximum gain.
- Kernel native scroll disabled only after both virtual output paths pass preflight.
- Failure may remove scroll temporarily; must never remove pointer or clicks. Rollback restores kernel scroll.
- Runtime must remain event-driven and negligible versus current service load.
- Public installer must be least-privilege, transactional, hardware-specific, and reversible.
- Preserve upstream MIT notice and distinguish derived code from external inspiration.

§I

- `magic_mouse_gestures.py`: hidraw input, gesture detection, axis-lock state, scroll emission.
- `/dev/uinput` `Magic Mouse Scroll`: virtual device advertising only `REL_WHEEL`, `REL_HWHEEL`, `REL_WHEEL_HI_RES`, `REL_HWHEEL_HI_RES`.
- `/dev/uinput` `Magic Mouse Pinch`: separate type-B multitouch touchpad advertising touch/tool keys and absolute MT slots only; no relative axes or mouse buttons.
- `python3-evdev`: uinput API; packaged dependency.
- `SCROLL_SPEED=22`, `SCROLL_LOCK_RATIO=1.5`, `SCROLL_LOCK_TIMEOUT=0.25`, `SCROLL_ACCEL_MAX=2.3`, `PINCH_THRESHOLD_MM=2.0`, `PINCH_DOMINANCE=1.3`: optional environment overrides.
- `modprobe/99-magic-mouse-wayland-gestures.conf`: project-owned config with `scroll_acceleration=0`, `scroll_speed=22`, `emulate_scroll_wheel=0`, `emulate_3button=1`; userspace owns scroll, kernel owns clicks.
- `udev/99-magic-mouse-wayland-gestures.rules`: exact Magic Mouse 2 hidraw access plus active-session uinput access; never world-writable input devices.
- `systemd/magic-mouse-wayland-gestures.service`: restart/reconnect lifecycle with user-service hardening.
- `systemd/magic-mouse-wayland-gestures-ydotool.service`: project-specific keyboard-only ydotoold and private runtime socket.
- `tests/`: pure state-machine and integration-boundary tests; no physical mouse required.
- `THIRD_PARTY_NOTICES.md`, `LICENSE`, `README.md`, `RELEASE_CHECKLIST.md`: provenance, retained MIT notice, tested-platform boundary, public safety notes, and honest release gate.
- `.github/workflows/ci.yml`: syntax, lint, and unit verification; no incomplete PyPI publication.

§V

- V1: Program never grabs physical input device and never emits pointer motion or buttons.
- V2: Virtual uinput capabilities contain scroll axes only.
- V3: Exactly one active touch may produce scroll; zero or two-plus touches produce none.
- V4: Neutral state accumulates meaningful motion; locks only when one axis is at least `SCROLL_LOCK_RATIO` times other axis.
- V5: Locked state emits selected axis only. Orthogonal jitter always zero. Axis cannot switch while locked.
- V6: Finger lift unlocks immediately. Resting finger unlocks after `SCROLL_LOCK_TIMEOUT` without meaningful motion. Timeout never delays initial cardinal scrolling.
- V7: Low-resolution and high-resolution wheel accumulators preserve sub-step motion and emit Linux wheel-compatible values.
- V8: Speed default 22. Acceleration remains enabled but gain never exceeds `SCROLL_ACCEL_MAX` default 2.3.
- V9: Scroll path performs no subprocess calls, sleeps, periodic timers, or work without incoming HID data.
- V10: Existing two-finger Back/Forward recognition and ydotool keyboard-only behavior remain unchanged.
- V11: uinput initialization failure exits clearly before native scroll is disabled during install/deploy preflight.
- V12: Automated tests cover axis choice, jitter suppression, no mid-stream switch, timeout/lift release, finger-count isolation, acceleration cap, and scroll-only capabilities.
- V13: Install is idempotent. Documented rollback re-enables kernel scroll and removes userspace scroll ownership.
- V14: uinput preflight requires only runtime write access to `/dev/uinput`; it must not require read access to the virtual `/dev/input/event*` node or membership in broad `input` group.
- V15: While locked, only selected-axis motion refreshes lock activity; suppressed orthogonal motion cannot extend the lock beyond `SCROLL_LOCK_TIMEOUT` and may seed new-axis selection after expiry.
- V16: Userspace wheel signs match `hid-magicmouse`: positive parsed X emits positive horizontal wheel; positive parsed Y emits positive vertical wheel. Parser/output must not apply kernel Y negation twice.
- V17: Installer persists `emulate_3button=1`, applies it before Magic Mouse reprobe, and verifies the recreated physical input device advertises `BTN_MIDDLE`; no out-of-tree/DKMS mouse driver is installed.
- V18: Middle click is the kernel driver's center-zone physical click. Userspace never emits, grabs, or re-emits `BTN_LEFT`, `BTN_RIGHT`, or `BTN_MIDDLE`.
- V19: `Magic Mouse Pinch` is a second uinput device with type-B MT slots, `BTN_TOUCH`, finger-count tool keys, and `INPUT_PROP_POINTER`; it has no `EV_REL`, `BTN_LEFT`, `BTN_RIGHT`, or `BTN_MIDDLE`, and uses `max_effects=0`.
- V20: Pinch may start only with exactly two stable touch IDs when finger-distance change is at least `PINCH_THRESHOLD_MM` and at least `PINCH_DOMINANCE` times centroid travel. Zero, one, or three-plus touches never emit pinch.
- V21: Pinch output starts two tracking slots at scale 1, updates symmetric positions around a fixed center using absolute scale, and releases both slots on lift, ID change, reconnect, or shutdown.
- V22: Pinch and Back/Forward are mutually exclusive for each two-finger contact sequence. Pinch suppresses ydotool navigation; recognized swipe locks out pinch until all contacts lift.
- V23: Preflight creates and closes both runtime uinput devices without reading their event nodes. Failure occurs before native scroll is disabled or middle-click reprobe begins.
- V24: Automated tests cover middle-click configuration/order, pinch capability isolation, threshold/dominance, slot lifecycle, scale direction, finger-count isolation, and pinch-vs-swipe locking. Live verification checks `BTN_MIDDLE`, libinput `pointer gesture`, active service, and clean logs.
- V25: Installer installs and reloads its exact udev rules before uinput preflight, but changes neither live nor persistent kernel scroll ownership until both virtual devices pass. It never requires membership in broad `input` group.
- V26: Installer owns a uniquely named modprobe file and registers rollback before any kernel setting changes. Every later failure restores native live scroll and removes the project-owned persistent config; it never overwrites a generic user config.
- V27: Bluetooth reprobe targets only an unambiguous paired device whose name contains `Magic Mouse`; it never falls back to an arbitrary connected mouse. Missing or ambiguous matches require manual power-cycle guidance.
- V28: Udev grants the active local session only the required exact Magic Mouse 2 hidraw and uinput access. No project rule uses `MODE=0666`.
- V29: Navigation uses a project-specific keyboard-only ydotoold and socket, never overrides the shared `ydotool.service`; uninstall removes only explicit project-owned paths/services, restores native live scroll and default middle-click state, and contains no recursive deletion.
- V30: Public metadata consistently names `magic-mouse-wayland-gestures`, targets `Salacfrantisek`, preserves Breno Perucchi's MIT copyright, credits inspiration without claiming copied GPL/kernel code, documents the tested hardware boundary, and has no PyPI publish path until system assets can be packaged correctly.
- V31: Runtime has one state reset per transition, catches only actionable key-send failures, never advises running the service as root, and keeps uinput tracking IDs within their advertised range.
- V32: User service applies safe process/filesystem hardening without hiding `/dev/hidraw*`, `/dev/uinput`, the ydotool socket, or required system libraries.

§T

id|status|goal|cites
T1|x|Implement, test, document, preflight, and deploy minimal scroll-only sticky axis lock|V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,I.magic_mouse_gestures.py,I./dev/uinput,I.python3-evdev,I.modprobe/99-magic-mouse-wayland-gestures.conf,I.systemd/magic-mouse-wayland-gestures.service,I.tests
T2|x|Enable, test, document, and deploy kernel-native center-zone middle click|V1,V11,V13,V17,V18,V24,I.modprobe/99-magic-mouse-wayland-gestures.conf,I.tests
T3|x|Implement, test, document, preflight, deploy, and package native Wayland pinch without swipe/scroll regressions|V1,V2,V3,V9,V10,V11,V12,V13,V14,V18,V19,V20,V21,V22,V23,V24,I.magic_mouse_gestures.py,I./dev/uinput,I.python3-evdev,I.systemd/magic-mouse-wayland-gestures.service,I.tests
T4|x|Prepare clean public derivative with least-privilege transactional install, accurate provenance, safe uninstall, CI, and publication metadata|V1,V11,V13,V14,V17,V18,V19,V23,V24,V25,V26,V27,V28,V29,V30,V31,V32,I.magic_mouse_gestures.py,I.modprobe/99-magic-mouse-wayland-gestures.conf,I.udev/99-magic-mouse-wayland-gestures.rules,I.systemd/magic-mouse-wayland-gestures.service,I.tests,I.THIRD_PARTY_NOTICES.md,I.LICENSE,I.README.md,I.github/workflows/ci.yml

§B

id|date|cause|fix
B1|2026-08-10|preflight read virtual event node though runtime only writes uinput|V14
B2|2026-08-10|suppressed orthogonal motion refreshed lock timeout indefinitely|V15
B3|2026-08-10|uinput default advertised unused force-feedback event type|V2
B4|2026-08-10|userspace output repeated kernel Y negation absent from parser|V16
B5|2026-08-12|fresh install checked uinput before installing its access rule|V25
B6|2026-08-12|late install failure could leave persistent native scroll disabled|V26
B7|2026-08-12|device reprobe fallback could select an unrelated connected mouse|V27
B8|2026-08-12|hidraw rule granted all local accounts read/write access|V28
B9|2026-08-12|shared ydotool override leaked across uninstall and recursive deletion was broader than required|V29
B10|2026-08-12|inherited publication metadata and PyPI workflow did not describe complete system integration|V30
B11|2026-08-12|key-send caught every exception and tracking IDs could exceed advertised range|V31
B12|2026-08-12|static tests expected expanded shell literals instead of project-path expressions|V26,V29
B13|2026-08-12|publication lint found unsorted imports and ambiguous sudo redirection|V30
B14|2026-08-12|daemon preflight wrongly required socket removal though ydotoold securely replaces its stale 0600 socket|V29
B15|2026-08-12|release secret scan matched forbidden strings inside negative test assertions|V30
