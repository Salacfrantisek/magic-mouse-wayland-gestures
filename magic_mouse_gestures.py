#!/usr/bin/env python3
"""
Magic Mouse 2 Gesture Driver for Linux

Adds scroll, navigation, native pinch, and native three-finger swipe gestures
for Apple Magic Mouse 2 on Linux/Wayland while leaving pointer movement and
physical buttons in the kernel driver.

Derived from Breno Perucchi's magic-mouse-gestures project.
See THIRD_PARTY_NOTICES.md. License: MIT.
"""

import glob
import math
import os
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    from evdev import AbsInfo, UInput, ecodes
    from evdev.uinput import UInputError
except ImportError:  # Reported clearly by ScrollEmitter when used.
    AbsInfo = None
    UInput = None
    ecodes = None
    UInputError = OSError

__version__ = "0.1.0"

# Supported Bluetooth Magic Mouse identifiers
BUS_ID = "0005"
VENDOR_ID = "004c"
PRODUCT_IDS = frozenset(("0269", "0323"))
BTN_MIDDLE_CODE = 274
KEY_LEFT_ALT = 56
KEY_LEFT = 105
KEY_RIGHT = 106

# Touch coordinates are 12-bit (0-4095)
COORD_MAX = 4096

# Touch states - only these indicate active contact
# States 1-4 are contact, states 5-7 are lift/transitional
CONTACT_STATES = {1, 2, 3, 4}

# Reconnection settings
RECONNECT_DELAY_INITIAL = 1.0   # Initial delay before reconnect attempt
RECONNECT_DELAY_MAX = 30.0      # Maximum delay between attempts
RECONNECT_DELAY_MULTIPLIER = 2  # Exponential backoff multiplier
ERROR_THRESHOLD = 10            # Consecutive errors before reconnect
UINPUT_RETRY_DELAY_MAX = 5.0

# Kernel hid-magicmouse-compatible high-resolution wheel units.
SCROLL_HR_STEPS = 10
SCROLL_HR_MULT = 120 // SCROLL_HR_STEPS
SCROLL_LOCK_THRESHOLD = 90
SCROLL_ACCEL_BASE = 7
SCROLL_ACCEL_WINDOW = 0.5

# Magic Mouse touch-surface resolution used by hid-magicmouse.
MOUSE_RES_X = 26.0
MOUSE_RES_Y = 70.0

# The virtual touchpad emits a pure, fixed-center pinch. Libinput turns the
# type-B multitouch sequence into the same Wayland pinch protocol used by a
# physical touchpad.
PINCH_COORD_MAX = 4095
PINCH_COORD_CENTER = PINCH_COORD_MAX // 2
PINCH_BASE_HALF_SPAN = 700
PINCH_MIN_SCALE = 0.25
PINCH_MAX_SCALE = 2.5
PINCH_TRACKING_ID_MAX = 65535
SWIPE_BASE_CONTACTS = (
    (PINCH_COORD_CENTER - 700, PINCH_COORD_CENTER),
    (PINCH_COORD_CENTER, PINCH_COORD_CENTER),
    (PINCH_COORD_CENTER + 700, PINCH_COORD_CENTER),
)
VIRTUAL_TOUCHPAD_RESOLUTION = 45.0


def get_env_float(name: str, default: float) -> float:
    """Get float value from environment variable."""
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def get_env_int(name: str, default: int) -> int:
    """Get int value from environment variable."""
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Configurable thresholds via environment variables
SWIPE_THRESHOLD = get_env_int('SWIPE_THRESHOLD', 200)        # Min horizontal movement
SWIPE_VERTICAL_MAX = get_env_int('SWIPE_VERTICAL_MAX', 150)  # Max vertical movement
SWIPE_TIME_MAX = get_env_float('SWIPE_TIME_MAX', 0.5)        # Max swipe duration (seconds)
SWIPE_VELOCITY_MIN = get_env_int('SWIPE_VELOCITY_MIN', 200)  # Min horizontal velocity (px/s)
SCROLL_COOLDOWN = get_env_float('SCROLL_COOLDOWN', 0.25)     # Cooldown after scroll (seconds)
MIN_FINGERS = get_env_int('MIN_FINGERS', 2)                  # Preserve one-finger native scrolling
MAX_FINGERS = get_env_int('MAX_FINGERS', 2)                  # Max fingers (ignore >2)

SCROLL_SPEED = max(0, min(63, get_env_int('SCROLL_SPEED', 22)))
SCROLL_LOCK_RATIO = max(1.0, get_env_float('SCROLL_LOCK_RATIO', 1.5))
SCROLL_LOCK_TIMEOUT = max(0.0, get_env_float('SCROLL_LOCK_TIMEOUT', 0.25))
SCROLL_ACCEL_MAX = max(1.0, get_env_float('SCROLL_ACCEL_MAX', 2.3))
PINCH_THRESHOLD_MM = max(0.1, get_env_float('PINCH_THRESHOLD_MM', 2.0))
PINCH_DOMINANCE = max(1.0, get_env_float('PINCH_DOMINANCE', 1.3))

DEBUG = os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes')


def wrap_delta(new: int, old: int) -> int:
    """
    Calculate delta handling 12-bit coordinate wraparound.

    When touch coordinates wrap from 4095 to 0 (or vice versa),
    naive subtraction gives wrong results. This calculates the
    shortest distance accounting for wraparound.
    """
    delta = new - old
    if delta > COORD_MAX // 2:
        delta -= COORD_MAX
    elif delta < -COORD_MAX // 2:
        delta += COORD_MAX
    return delta


def capability_bitmap_has_code(bitmap_text: str, code: int) -> bool:
    """Return whether a sysfs capability bitmap contains one input code."""
    word_bits = struct.calcsize("L") * 8
    bitmap = 0
    for index, word in enumerate(reversed(bitmap_text.split())):
        bitmap |= int(word, 16) << (index * word_bits)
    return bool(bitmap & (1 << code))


def physical_middle_click_available(input_root: str = "/sys/class/input") -> bool:
    """Check that the reprobed physical Magic Mouse advertises BTN_MIDDLE."""
    for device_path in glob.glob(f"{input_root}/event*/device"):
        try:
            with open(f"{device_path}/id/vendor", "r", encoding="ascii") as vendor_file:
                vendor = vendor_file.read().strip().lower()
            with open(f"{device_path}/id/product", "r", encoding="ascii") as product_file:
                product = product_file.read().strip().lower()
            if vendor != VENDOR_ID or product not in PRODUCT_IDS:
                continue
            with open(f"{device_path}/capabilities/key", "r", encoding="ascii") as key_file:
                return capability_bitmap_has_code(key_file.read(), BTN_MIDDLE_CODE)
        except (OSError, ValueError):
            continue
    return False


@dataclass
class Touch:
    """Single touch point on the Magic Mouse surface"""
    id: int
    x: int
    y: int
    major: int
    minor: int
    size: int
    orientation: int
    state: int


@dataclass
class GestureState:
    """Tracks ongoing gesture state"""
    start_x: Optional[int] = None
    start_y: Optional[int] = None
    start_time: Optional[float] = None
    finger_count: int = 0
    last_gesture_time: float = 0
    last_scroll_time: float = 0


@dataclass(frozen=True)
class ScrollDelta:
    """Linux low- and high-resolution scroll values for one HID report."""
    horizontal: int = 0
    vertical: int = 0
    horizontal_hi_res: int = 0
    vertical_hi_res: int = 0

    def has_events(self) -> bool:
        return any((
            self.horizontal,
            self.vertical,
            self.horizontal_hi_res,
            self.vertical_hi_res,
        ))


@dataclass(frozen=True)
class PinchDecision:
    """One transition in the mutually exclusive two-finger gesture state."""
    phase: Optional[str] = None
    scale: float = 1.0
    reset_swipe: bool = False


class TwoFingerGestureArbiter:
    """Lock one contact sequence to pinch or browser navigation."""

    def __init__(
        self,
        threshold_mm: float = PINCH_THRESHOLD_MM,
        dominance: float = PINCH_DOMINANCE,
    ):
        self.threshold_mm = max(0.1, threshold_mm)
        self.dominance = max(1.0, dominance)
        self.mode: Optional[str] = None
        self._touch_ids: Optional[Tuple[int, int]] = None
        self._start_positions: Dict[int, Tuple[int, int]] = {}
        self._start_distance_mm: Optional[float] = None

    @staticmethod
    def _positions(touches: List[Touch]) -> Dict[int, Tuple[int, int]]:
        return {touch.id: (touch.x, touch.y) for touch in touches}

    @staticmethod
    def _distance_mm(positions: Dict[int, Tuple[int, int]]) -> float:
        first_id, second_id = sorted(positions)
        first_x, first_y = positions[first_id]
        second_x, second_y = positions[second_id]
        delta_x_mm = wrap_delta(second_x, first_x) / MOUSE_RES_X
        delta_y_mm = wrap_delta(second_y, first_y) / MOUSE_RES_Y
        return math.hypot(delta_x_mm, delta_y_mm)

    def _centroid_travel_mm(self, positions: Dict[int, Tuple[int, int]]) -> float:
        delta_x = 0.0
        delta_y = 0.0
        for touch_id in self._touch_ids or ():
            start_x, start_y = self._start_positions[touch_id]
            current_x, current_y = positions[touch_id]
            delta_x += wrap_delta(current_x, start_x) / MOUSE_RES_X
            delta_y += wrap_delta(current_y, start_y) / MOUSE_RES_Y
        return math.hypot(delta_x / 2.0, delta_y / 2.0)

    def reset(self) -> None:
        self.mode = None
        self._touch_ids = None
        self._start_positions = {}
        self._start_distance_mm = None

    def lock_swipe(self) -> None:
        """Prevent a recognized navigation swipe from becoming pinch later."""
        if self._touch_ids is not None and self.mode != "pinch":
            self.mode = "swipe"

    def update(self, touches: List[Touch]) -> PinchDecision:
        positions = self._positions(touches)
        touch_ids = tuple(sorted(positions))

        if len(touches) != 2 or len(touch_ids) != 2:
            phase = "end" if self.mode == "pinch" else None
            self.reset()
            return PinchDecision(phase=phase, reset_swipe=True)

        if self._touch_ids != touch_ids:
            phase = "end" if self.mode == "pinch" else None
            self.reset()
            self._touch_ids = touch_ids
            self._start_positions = positions
            self._start_distance_mm = self._distance_mm(positions)
            return PinchDecision(phase=phase, reset_swipe=True)

        if self._start_distance_mm is None or self._start_distance_mm <= 0.0:
            self._start_positions = positions
            self._start_distance_mm = self._distance_mm(positions)
            return PinchDecision()

        if self.mode == "swipe":
            return PinchDecision()

        distance_mm = self._distance_mm(positions)
        scale = distance_mm / self._start_distance_mm

        if self.mode == "pinch":
            return PinchDecision(phase="update", scale=scale)

        distance_change_mm = abs(distance_mm - self._start_distance_mm)
        centroid_travel_mm = self._centroid_travel_mm(positions)
        if (
            distance_change_mm >= self.threshold_mm
            and distance_change_mm >= centroid_travel_mm * self.dominance
        ):
            self.mode = "pinch"
            return PinchDecision(phase="begin", scale=scale)

        return PinchDecision()


class ScrollAxisLock:
    """Pure one-finger scroll filter with a sticky, inactivity-based axis lock."""

    def __init__(
        self,
        speed: int = SCROLL_SPEED,
        lock_ratio: float = SCROLL_LOCK_RATIO,
        lock_timeout: float = SCROLL_LOCK_TIMEOUT,
        acceleration_max: float = SCROLL_ACCEL_MAX,
        lock_threshold: int = SCROLL_LOCK_THRESHOLD,
    ):
        self.speed = max(0, min(63, speed))
        self.lock_ratio = max(1.0, lock_ratio)
        self.lock_timeout = max(0.0, lock_timeout)
        self.acceleration_max = max(1.0, acceleration_max)
        self.lock_threshold = max(1, lock_threshold)

        self.axis: Optional[str] = None
        self.touch_id: Optional[int] = None
        self.last_x: Optional[int] = None
        self.last_y: Optional[int] = None
        self.last_motion_time: Optional[float] = None
        self.last_output_time: Optional[float] = None
        self.acceleration_gain = 1.0
        self._acceleration_divisor = SCROLL_ACCEL_BASE
        self._pending_x = 0
        self._pending_y = 0
        self._raw_remainder = 0.0
        self._v120_remainder = 0

    def reset(self, clear_acceleration: bool = False) -> None:
        """End current touch sequence without affecting the physical device."""
        self.axis = None
        self.touch_id = None
        self.last_x = None
        self.last_y = None
        self.last_motion_time = None
        self._pending_x = 0
        self._pending_y = 0
        self._raw_remainder = 0.0
        self._v120_remainder = 0
        if clear_acceleration:
            self.last_output_time = None
            self.acceleration_gain = 1.0
            self._acceleration_divisor = SCROLL_ACCEL_BASE

    def _unlock(self) -> None:
        self.axis = None
        self._pending_x = 0
        self._pending_y = 0
        self._raw_remainder = 0.0
        self._v120_remainder = 0

    def _start_touch(self, touch: Touch, now: float) -> None:
        if (
            self.last_output_time is not None
            and now - self.last_output_time < SCROLL_ACCEL_WINDOW
        ):
            self._acceleration_divisor = max(
                1, self._acceleration_divisor - 1
            )
        else:
            self._acceleration_divisor = SCROLL_ACCEL_BASE

        self.acceleration_gain = min(
            self.acceleration_max,
            SCROLL_ACCEL_BASE / self._acceleration_divisor,
        )
        self._unlock()
        self.touch_id = touch.id
        self.last_x = touch.x
        self.last_y = touch.y
        self.last_motion_time = now

    def _maybe_lock_axis(self) -> None:
        abs_x = abs(self._pending_x)
        abs_y = abs(self._pending_y)

        if abs_x >= self.lock_threshold and abs_x >= abs_y * self.lock_ratio:
            self.axis = 'x'
        elif abs_y >= self.lock_threshold and abs_y >= abs_x * self.lock_ratio:
            self.axis = 'y'

        if self.axis is not None:
            # Initial motion is the same intent threshold used by the kernel.
            # Drop it so locking does not cause a visible jump.
            self._pending_x = 0
            self._pending_y = 0
            self._raw_remainder = 0.0
            self._v120_remainder = 0

    def _convert_axis_delta(self, raw_delta: int, now: float) -> ScrollDelta:
        raw_per_hi_res_step = max(
            ((64 - self.speed) * SCROLL_ACCEL_BASE)
            / (SCROLL_HR_STEPS * self.acceleration_gain),
            1.0,
        )
        self._raw_remainder += raw_delta
        hi_res_steps = math.trunc(self._raw_remainder / raw_per_hi_res_step)
        self._raw_remainder -= hi_res_steps * raw_per_hi_res_step

        hi_res_value = hi_res_steps * SCROLL_HR_MULT
        self._v120_remainder += hi_res_value
        low_res_value = math.trunc(self._v120_remainder / 120)
        self._v120_remainder -= low_res_value * 120

        if hi_res_value or low_res_value:
            self.last_output_time = now

        if self.axis == 'x':
            return ScrollDelta(
                horizontal=low_res_value,
                horizontal_hi_res=hi_res_value,
            )
        return ScrollDelta(
            vertical=low_res_value,
            vertical_hi_res=hi_res_value,
        )

    def update(
        self,
        touches: List[Touch],
        now: Optional[float] = None,
    ) -> ScrollDelta:
        """Consume one HID sample. Two-finger gestures never enter scroll."""
        if now is None:
            now = time.monotonic()

        if len(touches) != 1:
            self.reset()
            return ScrollDelta()

        touch = touches[0]
        if self.touch_id != touch.id or self.last_x is None or self.last_y is None:
            self._start_touch(touch, now)
            return ScrollDelta()

        delta_x = wrap_delta(touch.x, self.last_x)
        delta_y = wrap_delta(touch.y, self.last_y)
        self.last_x = touch.x
        self.last_y = touch.y

        if delta_x == 0 and delta_y == 0:
            return ScrollDelta()

        if self.axis is not None:
            if (
                self.last_motion_time is not None
                and now - self.last_motion_time >= self.lock_timeout
            ):
                self._unlock()
            else:
                selected_delta = delta_x if self.axis == 'x' else delta_y
                if selected_delta == 0:
                    return ScrollDelta()
                self.last_motion_time = now
                return self._convert_axis_delta(selected_delta, now)

        if self.axis is None:
            self.last_motion_time = now
            self._pending_x += delta_x
            self._pending_y += delta_y
            self._maybe_lock_axis()
            return ScrollDelta()

        return ScrollDelta()


def scroll_capabilities() -> Dict[int, List[int]]:
    """Capabilities are deliberately unable to move or click the pointer."""
    if ecodes is None:
        raise RuntimeError("python3-evdev is required for userspace scrolling")
    return {
        ecodes.EV_REL: [
            ecodes.REL_WHEEL,
            ecodes.REL_HWHEEL,
            ecodes.REL_WHEEL_HI_RES,
            ecodes.REL_HWHEEL_HI_RES,
        ]
    }


class ScrollEmitter:
    """Thin scroll-only /dev/uinput adapter."""

    def __init__(self, device_factory=None):
        if UInput is None or ecodes is None:
            raise RuntimeError("python3-evdev is required for userspace scrolling")
        if device_factory is None:
            device_factory = UInput
        try:
            self.device = device_factory(
                events=scroll_capabilities(),
                name="Magic Mouse Scroll",
                bustype=ecodes.BUS_VIRTUAL,
                max_effects=0,
            )
        except (OSError, UInputError) as error:
            raise RuntimeError(f"cannot create scroll-only uinput device: {error}") from error

    def emit(self, delta: ScrollDelta) -> None:
        if not delta.has_events():
            return
        events = (
            (ecodes.REL_HWHEEL, delta.horizontal),
            (ecodes.REL_WHEEL, delta.vertical),
            (ecodes.REL_HWHEEL_HI_RES, delta.horizontal_hi_res),
            (ecodes.REL_WHEEL_HI_RES, delta.vertical_hi_res),
        )
        for code, value in events:
            if value:
                self.device.write(ecodes.EV_REL, code, value)
        self.device.syn()

    def close(self) -> None:
        self.device.close()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()


def gesture_capabilities() -> Dict[int, List]:
    """Capabilities for the isolated pinch and three-finger touchpad."""
    if AbsInfo is None or ecodes is None:
        raise RuntimeError("python3-evdev is required for native pinch output")

    position = AbsInfo(
        value=PINCH_COORD_CENTER,
        min=0,
        max=PINCH_COORD_MAX,
        fuzz=0,
        flat=0,
        resolution=45,
    )
    return {
        ecodes.EV_KEY: [
            ecodes.BTN_TOUCH,
            ecodes.BTN_TOOL_FINGER,
            ecodes.BTN_TOOL_DOUBLETAP,
            ecodes.BTN_TOOL_TRIPLETAP,
        ],
        ecodes.EV_ABS: [
            (ecodes.ABS_X, position),
            (ecodes.ABS_Y, position),
            (
                ecodes.ABS_MT_SLOT,
                AbsInfo(value=0, min=0, max=2, fuzz=0, flat=0, resolution=0),
            ),
            (ecodes.ABS_MT_POSITION_X, position),
            (ecodes.ABS_MT_POSITION_Y, position),
            (
                ecodes.ABS_MT_TRACKING_ID,
                AbsInfo(value=0, min=0, max=65535, fuzz=0, flat=0, resolution=0),
            ),
        ],
    }


class GestureEmitter:
    """Gesture-only type-B touchpad; never emits a mouse button or REL axis."""

    def __init__(self, device_factory=None):
        if UInput is None or ecodes is None:
            raise RuntimeError("python3-evdev is required for native pinch output")
        if device_factory is None:
            device_factory = UInput
        try:
            self.device = device_factory(
                events=gesture_capabilities(),
                name="Magic Mouse Gesture Touchpad",
                bustype=ecodes.BUS_VIRTUAL,
                vendor=0x0001,
                product=0x0002,
                version=0x0001,
                input_props=[ecodes.INPUT_PROP_POINTER],
                max_effects=0,
            )
        except (OSError, UInputError) as error:
            raise RuntimeError(f"cannot create gesture-only uinput device: {error}") from error
        self.active = False
        self.three_finger_active = False
        self._three_finger_sequence = False
        self._swipe_touch_ids: Optional[Tuple[int, int, int]] = None
        self._swipe_start_positions: Dict[int, Tuple[int, int]] = {}
        self._next_tracking_id = 1

    def _advance_tracking_id(self, contact_count: int) -> None:
        if self._next_tracking_id > PINCH_TRACKING_ID_MAX - contact_count:
            self._next_tracking_id = 1
        else:
            self._next_tracking_id += contact_count

    @staticmethod
    def _coordinates(scale: float) -> Tuple[int, int]:
        clamped_scale = min(PINCH_MAX_SCALE, max(PINCH_MIN_SCALE, scale))
        half_span = round(PINCH_BASE_HALF_SPAN * clamped_scale)
        return (
            max(0, PINCH_COORD_CENTER - half_span),
            min(PINCH_COORD_MAX, PINCH_COORD_CENTER + half_span),
        )

    def _write_positions(self, scale: float, new_contacts: bool) -> None:
        left_x, right_x = self._coordinates(scale)
        if new_contacts:
            self.device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
            self.device.write(ecodes.EV_KEY, ecodes.BTN_TOOL_DOUBLETAP, 1)
        self.device.write(ecodes.EV_ABS, ecodes.ABS_X, PINCH_COORD_CENTER)
        self.device.write(ecodes.EV_ABS, ecodes.ABS_Y, PINCH_COORD_CENTER)
        for slot, x_position in enumerate((left_x, right_x)):
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_SLOT, slot)
            if new_contacts:
                self.device.write(
                    ecodes.EV_ABS,
                    ecodes.ABS_MT_TRACKING_ID,
                    self._next_tracking_id + slot,
                )
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_POSITION_X, x_position)
            self.device.write(
                ecodes.EV_ABS,
                ecodes.ABS_MT_POSITION_Y,
                PINCH_COORD_CENTER,
            )
        self.device.syn()

    def begin(self, scale: float) -> None:
        if self.active:
            self.end()
        self._write_positions(1.0, new_contacts=True)
        self.active = True
        self._advance_tracking_id(2)
        self.update(scale)

    def update(self, scale: float) -> None:
        if self.active:
            self._write_positions(scale, new_contacts=False)

    def end(self) -> None:
        if not self.active:
            return
        for slot in (0, 1):
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_SLOT, slot)
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, -1)
        self.device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
        self.device.write(ecodes.EV_KEY, ecodes.BTN_TOOL_DOUBLETAP, 0)
        self.device.syn()
        self.active = False

    @staticmethod
    def _translated_swipe_contacts(
        touches: List[Touch],
        start_positions: Dict[int, Tuple[int, int]],
    ) -> Tuple[Tuple[int, int], ...]:
        delta_x = sum(
            wrap_delta(touch.x, start_positions[touch.id][0]) for touch in touches
        ) / 3.0
        delta_y = sum(
            wrap_delta(touch.y, start_positions[touch.id][1]) for touch in touches
        ) / 3.0
        virtual_x = round(delta_x / MOUSE_RES_X * VIRTUAL_TOUCHPAD_RESOLUTION)
        virtual_y = -round(delta_y / MOUSE_RES_Y * VIRTUAL_TOUCHPAD_RESOLUTION)
        min_x = -min(x for x, _y in SWIPE_BASE_CONTACTS)
        max_x = PINCH_COORD_MAX - max(x for x, _y in SWIPE_BASE_CONTACTS)
        min_y = -min(y for _x, y in SWIPE_BASE_CONTACTS)
        max_y = PINCH_COORD_MAX - max(y for _x, y in SWIPE_BASE_CONTACTS)
        virtual_x = min(max_x, max(min_x, virtual_x))
        virtual_y = min(max_y, max(min_y, virtual_y))
        return tuple(
            (base_x + virtual_x, base_y + virtual_y)
            for base_x, base_y in SWIPE_BASE_CONTACTS
        )

    def _write_three_finger_positions(
        self,
        touches: List[Touch],
        new_contacts: bool,
    ) -> None:
        touches = sorted(touches, key=lambda touch: touch.id)
        positions = self._translated_swipe_contacts(
            touches,
            self._swipe_start_positions,
        )
        center_x = sum(x for x, _y in positions) // 3
        center_y = sum(y for _x, y in positions) // 3
        if new_contacts:
            self.device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
            self.device.write(ecodes.EV_KEY, ecodes.BTN_TOOL_TRIPLETAP, 1)
        self.device.write(ecodes.EV_ABS, ecodes.ABS_X, center_x)
        self.device.write(ecodes.EV_ABS, ecodes.ABS_Y, center_y)
        for slot, (x_position, y_position) in enumerate(positions):
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_SLOT, slot)
            if new_contacts:
                self.device.write(
                    ecodes.EV_ABS,
                    ecodes.ABS_MT_TRACKING_ID,
                    self._next_tracking_id + slot,
                )
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_POSITION_X, x_position)
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_POSITION_Y, y_position)
        self.device.syn()

    def _begin_three_finger(self, touches: List[Touch]) -> None:
        self._swipe_touch_ids = tuple(sorted(touch.id for touch in touches))
        self._swipe_start_positions = {
            touch.id: (touch.x, touch.y) for touch in touches
        }
        self._write_three_finger_positions(touches, new_contacts=True)
        self.three_finger_active = True
        self._advance_tracking_id(3)

    def _end_three_finger(self) -> None:
        if not self.three_finger_active:
            return
        for slot in (0, 1, 2):
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_SLOT, slot)
            self.device.write(ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, -1)
        self.device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
        self.device.write(ecodes.EV_KEY, ecodes.BTN_TOOL_TRIPLETAP, 0)
        self.device.syn()
        self.three_finger_active = False
        self._swipe_touch_ids = None
        self._swipe_start_positions = {}

    def update_three_finger(self, touches: List[Touch]) -> bool:
        """Emit or retain ownership of one exactly-three-finger sequence."""
        touch_ids = tuple(sorted(touch.id for touch in touches))
        if self._three_finger_sequence:
            if len(touches) == 3 and touch_ids == self._swipe_touch_ids:
                self._write_three_finger_positions(touches, new_contacts=False)
            else:
                self._end_three_finger()
                if not touches:
                    self._three_finger_sequence = False
            return True

        if len(touches) != 3 or len(touch_ids) != 3:
            return False

        self._three_finger_sequence = True
        self._begin_three_finger(touches)
        return True

    def reset(self) -> None:
        """Release every virtual contact and unlock the physical sequence."""
        self.end()
        self._end_three_finger()
        self._three_finger_sequence = False

    def close(self) -> None:
        self.reset()
        self.device.close()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()


def supported_hid_uevent(content: str) -> bool:
    """Return whether a uevent contains one exact supported Bluetooth HID ID."""
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if key != "HID_ID" or not separator:
            continue
        fields = value.split(":")
        if len(fields) != 3:
            return False
        try:
            bus, vendor, product = (
                f"{int(field, 16):04x}" for field in fields
            )
        except ValueError:
            return False
        return bus == BUS_ID and vendor == VENDOR_ID and product in PRODUCT_IDS
    return False


def find_hidraw_device() -> Optional[str]:
    """
    Locate the hidraw device for Magic Mouse 2.

    Searches /dev/hidraw* devices and checks their vendor/product IDs
    against known Magic Mouse 2 identifiers.
    """
    for hidraw in glob.glob('/dev/hidraw*'):
        try:
            sysfs_path = f'/sys/class/hidraw/{os.path.basename(hidraw)}/device/uevent'
            if os.path.exists(sysfs_path):
                with open(sysfs_path, 'r') as f:
                    content = f.read()
                    if supported_hid_uevent(content):
                        return hidraw
        except (IOError, PermissionError):
            continue
    return None


def parse_touch(data: bytes, offset: int) -> Touch:
    """
    Parse 8 bytes of touch data into a Touch object.

    Magic Mouse 2 touch data format (8 bytes per finger):
    - Byte 0: X position LSB
    - Byte 1: Y MSB (4 bits) + X MSB (4 bits)
    - Byte 2: Y position LSB
    - Byte 3: Touch major axis
    - Byte 4: Touch minor axis
    - Byte 5: ID LSB (2 bits) + size (6 bits)
    - Byte 6: Orientation (6 bits) + ID MSB (2 bits)
    - Byte 7: State (4 bits) + reserved (4 bits)
    """
    tdata = data[offset:offset + 8]

    x = tdata[0] | ((tdata[1] & 0x0F) << 8)
    y = (tdata[2] << 4) | (tdata[1] >> 4)
    major = tdata[3]
    minor = tdata[4]
    size = tdata[5] & 0x3F
    id_lsb = (tdata[5] >> 6) & 0x03
    id_msb = tdata[6] & 0x03
    touch_id = id_lsb | (id_msb << 2)
    orientation = (tdata[6] >> 2) & 0x3F
    state = (tdata[7] >> 4) & 0x0F

    return Touch(
        id=touch_id, x=x, y=y,
        major=major, minor=minor,
        size=size, orientation=orientation,
        state=state
    )


def parse_report(data: bytes) -> List[Touch]:
    """
    Parse a complete HID report from the Magic Mouse 2.

    Report structure:
    - 14 bytes header (mouse movement data)
    - N * 8 bytes touch data (one block per detected finger)

    Only returns touches in active contact states (1-4).
    States 5-7 are lift/transitional and are filtered out.
    """
    if len(data) < 14:
        return []

    touches = []
    num_fingers = (len(data) - 14) // 8

    for i in range(num_fingers):
        offset = 14 + (i * 8)
        if offset + 8 <= len(data):
            touch = parse_touch(data, offset)
            # Only include active contact states, filter lift/transitional
            if touch.state in CONTACT_STATES and touch.size > 0:
                touches.append(touch)

    return touches


def send_key(key_code: int) -> bool:
    """Send Alt plus an arrow key via ydotool."""
    try:
        subprocess.run(
            [
                'ydotool', 'key',
                f'{KEY_LEFT_ALT}:1',
                f'{key_code}:1', f'{key_code}:0',
                f'{KEY_LEFT_ALT}:0',
            ],
            check=True,
            capture_output=True,
            timeout=2,
        )
        return True
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        if DEBUG:
            print(f"Key send failed: {error}", file=sys.stderr)
        return False


def reset_state(state: GestureState, avg_x: int, avg_y: int, now: float, finger_count: int):
    """Reset gesture tracking state."""
    state.start_x = avg_x
    state.start_y = avg_y
    state.start_time = now
    state.finger_count = finger_count


def clear_gesture_tracking(state: GestureState) -> None:
    """Clear only the active swipe sequence, preserving cooldown history."""
    state.start_x = None
    state.start_y = None
    state.start_time = None
    state.finger_count = 0


def process_touches(
    touches: List[Touch],
    state: GestureState,
    scroll_filter: ScrollAxisLock,
    scroll_emitter: ScrollEmitter,
    gesture_arbiter: TwoFingerGestureArbiter,
    gesture_emitter: GestureEmitter,
    key_sender=send_key,
) -> Optional[str]:
    """Route one HID sample to exactly one compatible gesture output path."""
    scroll_emitter.emit(scroll_filter.update(touches))
    pinch = gesture_arbiter.update(touches)
    if pinch.reset_swipe:
        clear_gesture_tracking(state)
    if pinch.phase == "end":
        gesture_emitter.end()

    if gesture_emitter.update_three_finger(touches) is True:
        clear_gesture_tracking(state)
        return "three_finger_swipe" if len(touches) == 3 else None

    if pinch.phase == "begin":
        clear_gesture_tracking(state)
        gesture_emitter.begin(pinch.scale)
    elif pinch.phase == "update":
        gesture_emitter.update(pinch.scale)

    if gesture_arbiter.mode == "pinch":
        return None

    gesture = detect_gesture(touches, state)
    if gesture == "swipe_left":
        gesture_arbiter.lock_swipe()
        if key_sender(KEY_RIGHT):
            print("→ Forward")
    elif gesture == "swipe_right":
        gesture_arbiter.lock_swipe()
        if key_sender(KEY_LEFT):
            print("← Back")
    return gesture


def _average_touch_position(touches: List[Touch]) -> Tuple[int, int]:
    """Return the integer centroid used by navigation detection."""
    finger_count = len(touches)
    return (
        sum(touch.x for touch in touches) // finger_count,
        sum(touch.y for touch in touches) // finger_count,
    )


def _horizontal_swipe_direction(
    delta_x: int,
    delta_y: int,
    elapsed: float,
) -> Optional[str]:
    """Classify a completed, horizontally dominant navigation movement."""
    if elapsed >= SWIPE_TIME_MAX or abs(delta_x) <= SWIPE_THRESHOLD:
        return None
    if abs(delta_x) / elapsed < SWIPE_VELOCITY_MIN:
        return None
    if abs(delta_x) <= abs(delta_y) * 3:
        return None
    return "swipe_right" if delta_x > 0 else "swipe_left"


def detect_gesture(touches: List[Touch], state: GestureState) -> Optional[str]:
    """Detect one deliberate two-finger horizontal navigation gesture."""
    now = time.monotonic()
    if now - state.last_gesture_time < 0.5:
        return None

    finger_count = len(touches)
    if not MIN_FINGERS <= finger_count <= MAX_FINGERS:
        if DEBUG and finger_count > MAX_FINGERS:
            print(f"Ignoring {finger_count} fingers (max={MAX_FINGERS})")
        clear_gesture_tracking(state)
        return None

    avg_x, avg_y = _average_touch_position(touches)
    tracking_missing = (
        state.start_x is None
        or state.start_y is None
        or state.start_time is None
    )
    if tracking_missing or finger_count != state.finger_count:
        if DEBUG and not tracking_missing:
            print(
                f"Finger count changed: {state.finger_count} -> "
                f"{finger_count}, resetting"
            )
        reset_state(state, avg_x, avg_y, now, finger_count)
        return None

    delta_x = wrap_delta(avg_x, state.start_x)
    delta_y = wrap_delta(avg_y, state.start_y)
    elapsed = now - state.start_time
    if elapsed < 0.01:
        return None

    if abs(delta_y) > SWIPE_VERTICAL_MAX or abs(delta_y) > abs(delta_x):
        if DEBUG:
            print(f"Scroll detected: delta_y={delta_y}, resetting")
        state.last_scroll_time = now
        reset_state(state, avg_x, avg_y, now, finger_count)
        return None
    if now - state.last_scroll_time < SCROLL_COOLDOWN:
        return None

    gesture = _horizontal_swipe_direction(delta_x, delta_y, elapsed)
    if gesture is not None:
        if DEBUG:
            velocity_x = abs(delta_x) / elapsed
            print(f"Swipe detected: delta_x={delta_x}, velocity={velocity_x:.0f}px/s")
        clear_gesture_tracking(state)
        state.last_gesture_time = now
        return gesture

    if elapsed > SWIPE_TIME_MAX:
        reset_state(state, avg_x, avg_y, now, finger_count)
    return None


def print_config() -> None:
    """Print current configuration."""
    print("Configuration:")
    print(f"  SWIPE_THRESHOLD    = {SWIPE_THRESHOLD} px")
    print(f"  SWIPE_VERTICAL_MAX = {SWIPE_VERTICAL_MAX} px")
    print(f"  SWIPE_TIME_MAX     = {SWIPE_TIME_MAX} s")
    print(f"  SWIPE_VELOCITY_MIN = {SWIPE_VELOCITY_MIN} px/s")
    print(f"  SCROLL_COOLDOWN    = {SCROLL_COOLDOWN} s")
    print(f"  MIN_FINGERS        = {MIN_FINGERS}")
    print(f"  MAX_FINGERS        = {MAX_FINGERS}")
    print(f"  SCROLL_SPEED       = {SCROLL_SPEED}")
    print(f"  SCROLL_LOCK_RATIO  = {SCROLL_LOCK_RATIO}")
    print(f"  SCROLL_LOCK_TIMEOUT= {SCROLL_LOCK_TIMEOUT} s")
    print(f"  SCROLL_ACCEL_MAX   = {SCROLL_ACCEL_MAX}x")
    print(f"  PINCH_THRESHOLD_MM = {PINCH_THRESHOLD_MM} mm")
    print(f"  PINCH_DOMINANCE    = {PINCH_DOMINANCE}x")
    print(f"  DEBUG              = {DEBUG}")
    print()


def run_device_loop(
    fd: int,
    state: GestureState,
    scroll_filter: ScrollAxisLock,
    scroll_emitter: ScrollEmitter,
    gesture_arbiter: TwoFingerGestureArbiter,
    gesture_emitter: GestureEmitter,
) -> bool:
    """
    Main device reading loop.

    Returns True if should attempt reconnect, False to exit.
    """
    consecutive_errors = 0

    while True:
        try:
            data = os.read(fd, 64)
            consecutive_errors = 0  # Reset on successful read
        except OSError as e:
            consecutive_errors += 1
            if DEBUG:
                print(f"Read error ({consecutive_errors}): {e}")

            if consecutive_errors >= ERROR_THRESHOLD:
                print("Device disconnected, attempting reconnect...")
                return True  # Signal reconnect

            time.sleep(0.1)  # Small delay before retry
            continue

        if not data:
            consecutive_errors += 1
            if consecutive_errors >= ERROR_THRESHOLD:
                print("Device not responding, attempting reconnect...")
                return True
            time.sleep(0.1)
            continue

        touches = parse_report(data)

        if DEBUG and touches:
            for t in touches:
                print(f"Touch: id={t.id} x={t.x} y={t.y} state={t.state}")

        process_touches(
            touches,
            state,
            scroll_filter,
            scroll_emitter,
            gesture_arbiter,
            gesture_emitter,
        )


def check_uinput(
    emitter_factory=ScrollEmitter,
    gesture_emitter_factory=GestureEmitter,
) -> bool:
    """Create and close both write-only virtual devices used at runtime."""
    try:
        with emitter_factory(), gesture_emitter_factory():
            pass
        print("uinput preflight OK: isolated scroll and gesture devices")
        return True
    except RuntimeError as error:
        print(f"uinput preflight failed: {error}", file=sys.stderr)
        return False


def wait_for_virtual_outputs(
    scroll_factory=ScrollEmitter,
    gesture_factory=GestureEmitter,
    sleep=time.sleep,
) -> Tuple[ScrollEmitter, GestureEmitter]:
    """Wait for boot-time uinput ACLs without crashing the user service."""
    retry_delay = RECONNECT_DELAY_INITIAL
    while True:
        scroll_emitter = None
        try:
            scroll_emitter = scroll_factory()
            gesture_emitter = gesture_factory()
            return scroll_emitter, gesture_emitter
        except RuntimeError as error:
            if scroll_emitter is not None:
                scroll_emitter.close()
            print(
                f"Virtual input not ready: {error}; retrying in "
                f"{retry_delay:.0f}s",
                file=sys.stderr,
            )
            sleep(retry_delay)
            retry_delay = min(
                retry_delay * RECONNECT_DELAY_MULTIPLIER,
                UINPUT_RETRY_DELAY_MAX,
            )


def main() -> int:
    """Main entry point with automatic reconnection."""
    if sys.argv[1:] == ['--check-uinput']:
        return 0 if check_uinput() else 1
    if sys.argv[1:] == ['--check-middle-click']:
        if physical_middle_click_available():
            print("middle-click check OK: physical device advertises BTN_MIDDLE")
            return 0
        print("middle-click check failed: BTN_MIDDLE is not advertised", file=sys.stderr)
        return 1
    if sys.argv[1:]:
        print(f"Unknown arguments: {' '.join(sys.argv[1:])}", file=sys.stderr)
        return 2

    print(f"Magic Mouse Wayland Gestures v{__version__}")
    print("=" * 35)

    if DEBUG:
        print_config()

    state = GestureState()
    scroll_filter = ScrollAxisLock()
    gesture_arbiter = TwoFingerGestureArbiter()
    reconnect_delay = RECONNECT_DELAY_INITIAL

    if UInput is None or ecodes is None:
        print("python3-evdev is required for virtual input output", file=sys.stderr)
        return 1
    scroll_emitter, gesture_emitter = wait_for_virtual_outputs()

    try:
        while True:
            # Find device
            hidraw = find_hidraw_device()
            if not hidraw:
                print(f"Magic Mouse not found, retrying in {reconnect_delay:.0f}s...")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * RECONNECT_DELAY_MULTIPLIER, RECONNECT_DELAY_MAX)
                continue

            # Open device
            try:
                fd = os.open(hidraw, os.O_RDONLY)
            except PermissionError:
                print(f"Permission denied for {hidraw}", file=sys.stderr)
                print("Install the project udev rules; do not run this service as root.")
                return 1
            except OSError as e:
                print(f"Failed to open {hidraw}: {e}")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * RECONNECT_DELAY_MULTIPLIER, RECONNECT_DELAY_MAX)
                continue

            # Connected successfully - reset backoff and stale state.
            reconnect_delay = RECONNECT_DELAY_INITIAL
            state.start_x = None
            state.start_y = None
            state.start_time = None
            state.finger_count = 0
            state.last_gesture_time = 0
            state.last_scroll_time = 0
            scroll_filter.reset(clear_acceleration=True)
            gesture_arbiter.reset()
            gesture_emitter.reset()

            print(f"Connected: {hidraw}")
            print("One finger scrolls; two fingers pinch or navigate back/forward")
            print("Three fingers use GNOME workspace and overview gestures")
            print("Press Ctrl+C to stop\n")

            try:
                should_reconnect = run_device_loop(
                    fd,
                    state,
                    scroll_filter,
                    scroll_emitter,
                    gesture_arbiter,
                    gesture_emitter,
                )
                if not should_reconnect:
                    break
            except KeyboardInterrupt:
                print("\nStopped")
                break
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass
                gesture_emitter.reset()
                gesture_arbiter.reset()

            print(f"Reconnecting in {reconnect_delay:.0f}s...")
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * RECONNECT_DELAY_MULTIPLIER, RECONNECT_DELAY_MAX)
    finally:
        gesture_emitter.close()
        scroll_emitter.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
