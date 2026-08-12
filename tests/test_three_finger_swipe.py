from unittest.mock import Mock

import magic_mouse_gestures as gestures


def make_touch(touch_id: int, x: int, y: int = 1000) -> gestures.Touch:
    return gestures.Touch(
        id=touch_id,
        x=x,
        y=y,
        major=10,
        minor=10,
        size=10,
        orientation=0,
        state=4,
    )


def three_touches(x_offset: int = 0, y_offset: int = 0):
    return [
        make_touch(0, 800 + x_offset, 1000 + y_offset),
        make_touch(1, 1600 + x_offset, 1000 + y_offset),
        make_touch(2, 2400 + x_offset, 1000 + y_offset),
    ]


def test_v36_gesture_device_has_three_slots_without_pointer_capabilities():
    capabilities = gestures.gesture_capabilities()

    assert gestures.ecodes.EV_REL not in capabilities
    assert gestures.ecodes.BTN_TOOL_TRIPLETAP in capabilities[gestures.ecodes.EV_KEY]
    assert gestures.ecodes.BTN_LEFT not in capabilities[gestures.ecodes.EV_KEY]
    assert gestures.ecodes.BTN_RIGHT not in capabilities[gestures.ecodes.EV_KEY]
    assert gestures.ecodes.BTN_MIDDLE not in capabilities[gestures.ecodes.EV_KEY]

    slot = next(
        abs_info
        for code, abs_info in capabilities[gestures.ecodes.EV_ABS]
        if code == gestures.ecodes.ABS_MT_SLOT
    )
    assert slot.max == 2


def test_v34_three_contacts_translate_equally_with_physical_centroid():
    fake_device = Mock()
    emitter = gestures.GestureEmitter(device_factory=Mock(return_value=fake_device))

    assert emitter.update_three_finger(three_touches())
    assert emitter.update_three_finger(three_touches(x_offset=260, y_offset=700))

    x_values = [
        call.args[2]
        for call in fake_device.write.call_args_list
        if call.args[:2] == (
            gestures.ecodes.EV_ABS,
            gestures.ecodes.ABS_MT_POSITION_X,
        )
    ]
    y_values = [
        call.args[2]
        for call in fake_device.write.call_args_list
        if call.args[:2] == (
            gestures.ecodes.EV_ABS,
            gestures.ecodes.ABS_MT_POSITION_Y,
        )
    ]

    assert x_values[3:] == [value + 450 for value in x_values[:3]]
    assert y_values[3:] == [value + 450 for value in y_values[:3]]


def test_v35_id_change_ends_output_and_locks_until_every_finger_lifts():
    fake_device = Mock()
    emitter = gestures.GestureEmitter(device_factory=Mock(return_value=fake_device))

    assert emitter.update_three_finger(three_touches())
    changed_ids = [
        make_touch(0, 800),
        make_touch(1, 1600),
        make_touch(3, 2400),
    ]
    assert emitter.update_three_finger(changed_ids)
    assert not emitter.three_finger_active
    assert emitter.update_three_finger(three_touches())
    assert not emitter.three_finger_active
    assert emitter.update_three_finger([])
    assert emitter.update_three_finger(three_touches())
    assert emitter.three_finger_active


def test_v35_drop_to_two_fingers_cannot_start_pinch_or_navigation():
    state = gestures.GestureState()
    scroll_filter = gestures.ScrollAxisLock()
    scroll_emitter = Mock()
    fake_device = Mock()
    gesture_emitter = gestures.GestureEmitter(
        device_factory=Mock(return_value=fake_device),
    )
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=0.1)
    key_sender = Mock(return_value=True)

    assert gestures.process_touches(
        three_touches(),
        state,
        scroll_filter,
        scroll_emitter,
        arbiter,
        gesture_emitter,
        key_sender,
    ) == "three_finger_swipe"
    assert gestures.process_touches(
        [make_touch(0, 600), make_touch(1, 1800)],
        state,
        scroll_filter,
        scroll_emitter,
        arbiter,
        gesture_emitter,
        key_sender,
    ) is None
    assert gestures.process_touches(
        [make_touch(0, 300), make_touch(1, 2100)],
        state,
        scroll_filter,
        scroll_emitter,
        arbiter,
        gesture_emitter,
        key_sender,
    ) is None
    key_sender.assert_not_called()
    assert not gesture_emitter.active


def test_v35_reset_releases_three_contacts_and_unlocks_sequence():
    fake_device = Mock()
    emitter = gestures.GestureEmitter(device_factory=Mock(return_value=fake_device))
    emitter.update_three_finger(three_touches())

    emitter.reset()

    assert not emitter.three_finger_active
    assert emitter.update_three_finger(three_touches())
    assert emitter.three_finger_active
