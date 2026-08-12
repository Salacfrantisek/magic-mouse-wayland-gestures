# Third-party notices and provenance

## Derived code

This project began from Breno Perucchi's
[`brenoperucchi/magic-mouse-gestures`](https://github.com/brenoperucchi/magic-mouse-gestures).
That repository is distributed under the MIT License. Its 2025 copyright and
permission notice are preserved in this repository's `LICENSE` file.

The retained foundation includes Magic Mouse 2 hidraw discovery and touch
report parsing, the reconnection loop, initial two-finger navigation detector,
installer structure, and documentation concepts. The implementation here was
then substantially changed to add userspace high-resolution scrolling, sticky
axis arbitration, native Wayland pinch through a separate virtual touchpad,
kernel-native middle-click setup, capability isolation, regression tests,
transactional installation, and least-privilege device access.

## Technical references; no source copied

- [`RicardoEPRodrigues/magicmouse-hid`](https://github.com/RicardoEPRodrigues/magicmouse-hid)
  was consulted for its description of Magic Mouse 2 report layout, middle
  click, and historical kernel support. This repository contains no source code
  copied from that kernel-driver repository.
- The Linux in-tree `hid_magicmouse` driver and its public module parameters
  were used to verify coordinate resolution, wheel conventions, and native
  middle-click behavior. No kernel-driver source is redistributed here.

## Local navigation experiment

An early local patch of unknown authorship suggested replacing `wtype` with
`ydotool`. Its proposed mouse-click commands were not retained. The final
implementation was rewritten to emit explicit keyboard-only `Alt+Left` and
`Alt+Right` sequences through `ydotoold --mouse-off`.

If you recognize that early patch and can provide its original source URL,
please open an issue so this notice can be made more specific.
