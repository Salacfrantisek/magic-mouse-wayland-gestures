from unittest.mock import Mock, patch

import pytest

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


def test_v19_pinch_device_has_only_touchpad_gesture_capabilities():
    capabilities = gestures.gesture_capabilities()

    assert gestures.ecodes.EV_REL not in capabilities
    assert set(capabilities[gestures.ecodes.EV_KEY]) == {
        gestures.ecodes.BTN_TOUCH,
        gestures.ecodes.BTN_TOOL_FINGER,
        gestures.ecodes.BTN_TOOL_DOUBLETAP,
        gestures.ecodes.BTN_TOOL_TRIPLETAP,
    }
    assert gestures.ecodes.BTN_LEFT not in capabilities[gestures.ecodes.EV_KEY]
    assert gestures.ecodes.BTN_RIGHT not in capabilities[gestures.ecodes.EV_KEY]
    assert gestures.ecodes.BTN_MIDDLE not in capabilities[gestures.ecodes.EV_KEY]

    abs_codes = {code for code, _abs_info in capabilities[gestures.ecodes.EV_ABS]}
    assert abs_codes == {
        gestures.ecodes.ABS_X,
        gestures.ecodes.ABS_Y,
        gestures.ecodes.ABS_MT_SLOT,
        gestures.ecodes.ABS_MT_POSITION_X,
        gestures.ecodes.ABS_MT_POSITION_Y,
        gestures.ecodes.ABS_MT_TRACKING_ID,
    }


def test_v19_pinch_emitter_is_separate_pointer_property_device():
    fake_device = Mock()
    factory = Mock(return_value=fake_device)

    gestures.GestureEmitter(device_factory=factory)

    factory.assert_called_once_with(
        events=gestures.gesture_capabilities(),
        name="Magic Mouse Gesture Touchpad",
        bustype=gestures.ecodes.BUS_VIRTUAL,
        vendor=0x0001,
        product=0x0002,
        version=0x0001,
        input_props=[gestures.ecodes.INPUT_PROP_POINTER],
        max_effects=0,
    )


def test_v19_pinch_uinput_initialization_failure_is_clear():
    def fail_factory(**_kwargs):
        raise PermissionError("denied")

    with pytest.raises(RuntimeError, match="cannot create gesture-only uinput device"):
        gestures.GestureEmitter(device_factory=fail_factory)


def test_v20_symmetric_distance_change_starts_outward_pinch():
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=2.0, dominance=1.3)

    assert arbiter.update([make_touch(0, 1000), make_touch(1, 2000)]).phase is None
    decision = arbiter.update([make_touch(0, 900), make_touch(1, 2100)])

    assert decision.phase == "begin"
    assert decision.scale == pytest.approx(1.2)
    assert arbiter.mode == "pinch"


def test_v20_inward_pinch_reports_scale_below_one():
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=2.0, dominance=1.3)
    arbiter.update([make_touch(0, 1000), make_touch(1, 2000)])

    decision = arbiter.update([make_touch(0, 1100), make_touch(1, 1900)])

    assert decision.phase == "begin"
    assert decision.scale == pytest.approx(0.8)


def test_v20_translation_dominates_small_separation_error():
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=2.0, dominance=1.3)
    arbiter.update([make_touch(0, 1000), make_touch(1, 2000)])

    decision = arbiter.update([make_touch(0, 1200), make_touch(1, 2280)])

    assert decision.phase is None
    assert arbiter.mode is None


def test_v20_non_two_finger_sequences_never_begin_pinch():
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=0.1)

    assert arbiter.update([]).phase is None
    assert arbiter.update([make_touch(0, 1000)]).phase is None
    assert arbiter.update(
        [make_touch(0, 800), make_touch(1, 1600), make_touch(2, 2400)]
    ).phase is None
    assert arbiter.mode is None


def test_v21_pinch_emitter_starts_updates_and_releases_both_slots():
    fake_device = Mock()
    emitter = gestures.GestureEmitter(device_factory=Mock(return_value=fake_device))

    emitter.begin(1.5)
    emitter.end()

    position_x_values = [
        call.args[2]
        for call in fake_device.write.call_args_list
        if call.args[:2] == (gestures.ecodes.EV_ABS, gestures.ecodes.ABS_MT_POSITION_X)
    ]
    assert position_x_values[:2] == [
        gestures.PINCH_COORD_CENTER - gestures.PINCH_BASE_HALF_SPAN,
        gestures.PINCH_COORD_CENTER + gestures.PINCH_BASE_HALF_SPAN,
    ]
    assert position_x_values[2] < position_x_values[0]
    assert position_x_values[3] > position_x_values[1]

    tracking_values = [
        call.args[2]
        for call in fake_device.write.call_args_list
        if call.args[:2] == (gestures.ecodes.EV_ABS, gestures.ecodes.ABS_MT_TRACKING_ID)
    ]
    assert tracking_values[:2] == [1, 2]
    assert tracking_values[-2:] == [-1, -1]
    assert fake_device.syn.call_count == 3
    assert not emitter.active


def test_v31_tracking_ids_wrap_within_advertised_range():
    fake_device = Mock()
    emitter = gestures.GestureEmitter(device_factory=Mock(return_value=fake_device))
    emitter._next_tracking_id = gestures.PINCH_TRACKING_ID_MAX - 1

    emitter.begin(1.1)
    emitter.end()
    emitter.begin(1.1)

    tracking_values = [
        call.args[2]
        for call in fake_device.write.call_args_list
        if call.args[:2] == (
            gestures.ecodes.EV_ABS,
            gestures.ecodes.ABS_MT_TRACKING_ID,
        )
        and call.args[2] >= 0
    ]
    assert tracking_values == [
        gestures.PINCH_TRACKING_ID_MAX - 1,
        gestures.PINCH_TRACKING_ID_MAX,
        1,
        2,
    ]


def test_v21_lift_ends_active_pinch_and_resets_sequence():
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=2.0)
    arbiter.update([make_touch(0, 1000), make_touch(1, 2000)])
    arbiter.update([make_touch(0, 900), make_touch(1, 2100)])

    decision = arbiter.update([])

    assert decision.phase == "end"
    assert decision.reset_swipe
    assert arbiter.mode is None


def test_v21_touch_id_change_ends_active_pinch():
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=2.0)
    arbiter.update([make_touch(0, 1000), make_touch(1, 2000)])
    arbiter.update([make_touch(0, 900), make_touch(1, 2100)])

    decision = arbiter.update([make_touch(0, 900), make_touch(2, 2100)])

    assert decision.phase == "end"
    assert decision.reset_swipe
    assert arbiter.mode is None


def test_v22_navigation_lock_prevents_late_pinch():
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=2.0)
    arbiter.update([make_touch(0, 1000), make_touch(1, 2000)])
    arbiter.update([make_touch(0, 1300), make_touch(1, 2300)])
    arbiter.lock_swipe()

    decision = arbiter.update([make_touch(0, 1100), make_touch(1, 2500)])

    assert decision.phase is None
    assert arbiter.mode == "swipe"


def test_v22_runtime_pinch_suppresses_navigation_sender():
    state = gestures.GestureState()
    scroll_filter = gestures.ScrollAxisLock()
    scroll_emitter = Mock()
    pinch_emitter = Mock()
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=2.0)
    key_sender = Mock(return_value=True)

    with patch.object(gestures.time, "monotonic", side_effect=[1.0, 1.0, 1.2]):
        gestures.process_touches(
            [make_touch(0, 1000), make_touch(1, 2000)],
            state,
            scroll_filter,
            scroll_emitter,
            arbiter,
            pinch_emitter,
            key_sender,
        )
        gesture = gestures.process_touches(
            [make_touch(0, 900), make_touch(1, 2100)],
            state,
            scroll_filter,
            scroll_emitter,
            arbiter,
            pinch_emitter,
            key_sender,
        )

    assert gesture is None
    pinch_emitter.begin.assert_called_once_with(pytest.approx(1.2))
    key_sender.assert_not_called()


def test_v22_runtime_swipe_locks_out_pinch_and_sends_back():
    state = gestures.GestureState()
    scroll_filter = gestures.ScrollAxisLock()
    scroll_emitter = Mock()
    pinch_emitter = Mock()
    arbiter = gestures.TwoFingerGestureArbiter(threshold_mm=2.0)
    key_sender = Mock(return_value=True)

    with patch.object(
        gestures.time,
        "monotonic",
        side_effect=[1.0, 1.0, 1.2, 1.2],
    ):
        gestures.process_touches(
            [make_touch(0, 1000), make_touch(1, 2000)],
            state,
            scroll_filter,
            scroll_emitter,
            arbiter,
            pinch_emitter,
            key_sender,
        )
        gesture = gestures.process_touches(
            [make_touch(0, 1400), make_touch(1, 2400)],
            state,
            scroll_filter,
            scroll_emitter,
            arbiter,
            pinch_emitter,
            key_sender,
        )

    assert gesture == "swipe_right"
    assert arbiter.mode == "swipe"
    pinch_emitter.begin.assert_not_called()
    key_sender.assert_called_once_with(gestures.KEY_LEFT)


def test_v23_preflight_creates_both_devices_without_capability_reads():
    scroll = Mock()
    scroll.__enter__ = Mock(return_value=scroll)
    scroll.__exit__ = Mock(return_value=None)
    pinch = Mock()
    pinch.__enter__ = Mock(return_value=pinch)
    pinch.__exit__ = Mock(return_value=None)

    assert gestures.check_uinput(
        emitter_factory=Mock(return_value=scroll),
        gesture_emitter_factory=Mock(return_value=pinch),
    )
    scroll.device.capabilities.assert_not_called()
    pinch.device.capabilities.assert_not_called()


def test_v31_key_sender_uses_bounded_keyboard_only_command():
    with patch.object(gestures.subprocess, "run") as run:
        assert gestures.send_key(gestures.KEY_LEFT)

    run.assert_called_once_with(
        [
            "ydotool",
            "key",
            f"{gestures.KEY_LEFT_ALT}:1",
            f"{gestures.KEY_LEFT}:1",
            f"{gestures.KEY_LEFT}:0",
            f"{gestures.KEY_LEFT_ALT}:0",
        ],
        check=True,
        capture_output=True,
        timeout=2,
    )


def test_v31_key_sender_catches_process_failures_but_not_programming_errors():
    with patch.object(
        gestures.subprocess,
        "run",
        side_effect=gestures.subprocess.TimeoutExpired("ydotool", 2),
    ):
        assert not gestures.send_key(gestures.KEY_LEFT)

    with patch.object(gestures.subprocess, "run", side_effect=ValueError("bug")):
        with pytest.raises(ValueError, match="bug"):
            gestures.send_key(gestures.KEY_LEFT)


def test_v33_uinput_error_is_wrapped_for_boot_retry():
    def fail_factory(**_kwargs):
        raise gestures.UInputError("ACL not ready")

    with pytest.raises(RuntimeError, match="cannot create scroll-only uinput device"):
        gestures.ScrollEmitter(device_factory=fail_factory)


def test_v33_boot_acl_retry_closes_partial_device_and_uses_bounded_backoff():
    failed_scrolls = [Mock() for _ in range(4)]
    successful_scroll = Mock()
    pinch = Mock()
    scroll_factory = Mock(side_effect=[*failed_scrolls, successful_scroll])
    gesture_factory = Mock(
        side_effect=[
            RuntimeError("ACL not ready"),
            RuntimeError("ACL not ready"),
            RuntimeError("ACL not ready"),
            RuntimeError("ACL not ready"),
            pinch,
        ]
    )
    sleep = Mock()

    result = gestures.wait_for_virtual_outputs(
        scroll_factory=scroll_factory,
        gesture_factory=gesture_factory,
        sleep=sleep,
    )

    assert result == (successful_scroll, pinch)
    for failed_scroll in failed_scrolls:
        failed_scroll.close.assert_called_once_with()
    successful_scroll.close.assert_not_called()
    assert [call.args[0] for call in sleep.call_args_list] == [
        1.0,
        2.0,
        4.0,
        gestures.UINPUT_RETRY_DELAY_MAX,
    ]
