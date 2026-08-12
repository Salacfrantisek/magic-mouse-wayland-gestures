from unittest.mock import Mock, patch

import pytest

import magic_mouse_gestures as gestures


def make_touch(x: int, y: int, touch_id: int = 0) -> gestures.Touch:
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


def start_filter(**kwargs) -> gestures.ScrollAxisLock:
    scroll_filter = gestures.ScrollAxisLock(**kwargs)
    assert scroll_filter.update([make_touch(1000, 1000)], now=1.0) == gestures.ScrollDelta()
    return scroll_filter


def test_v16_vertical_axis_matches_kernel_direction_without_delay():
    scroll_filter = start_filter(lock_timeout=0.25)

    assert scroll_filter.update([make_touch(1010, 1100)], now=1.01) == gestures.ScrollDelta()
    delta = scroll_filter.update([make_touch(1050, 1140)], now=1.02)

    assert scroll_filter.axis == 'y'
    assert delta.vertical_hi_res > 0
    assert delta.horizontal == 0
    assert delta.horizontal_hi_res == 0


def test_horizontal_axis_locks_and_suppresses_vertical_jitter():
    scroll_filter = start_filter()

    scroll_filter.update([make_touch(1100, 1010)], now=1.01)
    delta = scroll_filter.update([make_touch(1140, 1050)], now=1.02)

    assert scroll_filter.axis == 'x'
    assert delta.horizontal_hi_res > 0
    assert delta.vertical == 0
    assert delta.vertical_hi_res == 0


def test_diagonal_motion_waits_until_axis_is_dominant():
    scroll_filter = start_filter(lock_ratio=1.5)

    scroll_filter.update([make_touch(1100, 1090)], now=1.01)
    assert scroll_filter.axis is None

    scroll_filter.update([make_touch(1180, 1100)], now=1.02)
    assert scroll_filter.axis == 'x'


def test_locked_axis_cannot_switch_during_active_scroll():
    scroll_filter = start_filter(lock_timeout=0.25)
    scroll_filter.update([make_touch(1000, 1100)], now=1.01)

    delta = scroll_filter.update([make_touch(1200, 1100)], now=1.10)

    assert scroll_filter.axis == 'y'
    assert delta == gestures.ScrollDelta()


def test_inactivity_unlocks_before_new_axis_is_selected():
    scroll_filter = start_filter(lock_timeout=0.25)
    scroll_filter.update([make_touch(1000, 1100)], now=1.01)

    first = scroll_filter.update([make_touch(1100, 1100)], now=1.30)
    second = scroll_filter.update([make_touch(1140, 1100)], now=1.31)

    assert first == gestures.ScrollDelta()
    assert scroll_filter.axis == 'x'
    assert second.horizontal_hi_res > 0
    assert second.vertical_hi_res == 0


def test_v15_orthogonal_motion_cannot_extend_lock_timeout():
    scroll_filter = start_filter(lock_timeout=0.25)
    scroll_filter.update([make_touch(1100, 1000)], now=1.01)

    scroll_filter.update([make_touch(1100, 1040)], now=1.20)
    scroll_filter.update([make_touch(1100, 1080)], now=1.24)
    scroll_filter.update([make_touch(1100, 1130)], now=1.26)
    scroll_filter.update([make_touch(1100, 1230)], now=1.27)

    assert scroll_filter.axis == 'y'


def test_finger_lift_and_multiple_fingers_reset_scroll():
    scroll_filter = start_filter()
    scroll_filter.update([make_touch(1100, 1000)], now=1.01)

    assert scroll_filter.update([], now=1.02) == gestures.ScrollDelta()
    assert scroll_filter.axis is None
    assert scroll_filter.touch_id is None

    scroll_filter.update([make_touch(1000, 1000)], now=2.0)
    result = scroll_filter.update(
        [make_touch(1100, 1000), make_touch(1100, 1000, touch_id=1)],
        now=2.01,
    )
    assert result == gestures.ScrollDelta()
    assert scroll_filter.touch_id is None


def test_low_and_high_resolution_values_stay_in_sync():
    scroll_filter = start_filter(speed=22, acceleration_max=1.0)
    scroll_filter.update([make_touch(1100, 1000)], now=1.01)

    delta = scroll_filter.update([make_touch(1394, 1000)], now=1.02)

    assert delta.horizontal == 1
    assert delta.horizontal_hi_res == 120


def test_repeated_strokes_accelerate_but_never_exceed_cap():
    scroll_filter = gestures.ScrollAxisLock(acceleration_max=2.3)
    gains = []

    for index in range(7):
        now = 1.0 + index * 0.1
        touch_id = index % 16
        scroll_filter.update([make_touch(1000, 1000, touch_id)], now=now)
        gains.append(scroll_filter.acceleration_gain)
        scroll_filter.update([make_touch(1100, 1000, touch_id)], now=now + 0.01)
        scroll_filter.update([make_touch(1400, 1000, touch_id)], now=now + 0.02)
        scroll_filter.update([], now=now + 0.03)

    assert gains[0] == 1.0
    assert gains[-1] == pytest.approx(2.3)
    assert max(gains) <= 2.3


def test_scroll_filter_does_not_call_subprocess_sleep_or_uinput():
    scroll_filter = start_filter()

    with patch.object(gestures.subprocess, 'run') as subprocess_run, \
            patch.object(gestures.time, 'sleep') as sleep, \
            patch.object(gestures, 'UInput') as uinput:
        scroll_filter.update([make_touch(1100, 1000)], now=1.01)
        scroll_filter.update([make_touch(1140, 1000)], now=1.02)

    subprocess_run.assert_not_called()
    sleep.assert_not_called()
    uinput.assert_not_called()


def test_virtual_device_advertises_scroll_axes_only():
    capabilities = gestures.scroll_capabilities()

    assert capabilities == {
        gestures.ecodes.EV_REL: [
            gestures.ecodes.REL_WHEEL,
            gestures.ecodes.REL_HWHEEL,
            gestures.ecodes.REL_WHEEL_HI_RES,
            gestures.ecodes.REL_HWHEEL_HI_RES,
        ]
    }
    assert gestures.ecodes.REL_X not in capabilities[gestures.ecodes.EV_REL]
    assert gestures.ecodes.REL_Y not in capabilities[gestures.ecodes.EV_REL]
    assert gestures.ecodes.EV_KEY not in capabilities


def test_emitter_writes_only_nonzero_scroll_events():
    fake_device = Mock()
    factory = Mock(return_value=fake_device)
    emitter = gestures.ScrollEmitter(device_factory=factory)

    emitter.emit(gestures.ScrollDelta(horizontal=1, horizontal_hi_res=120))

    factory.assert_called_once_with(
        events=gestures.scroll_capabilities(),
        name='Magic Mouse Scroll',
        bustype=gestures.ecodes.BUS_VIRTUAL,
        max_effects=0,
    )
    assert fake_device.write.call_args_list == [
        ((gestures.ecodes.EV_REL, gestures.ecodes.REL_HWHEEL, 1),),
        ((gestures.ecodes.EV_REL, gestures.ecodes.REL_HWHEEL_HI_RES, 120),),
    ]
    fake_device.syn.assert_called_once_with()


def test_uinput_initialization_failure_is_clear():
    def fail_factory(**_kwargs):
        raise PermissionError('denied')

    with pytest.raises(RuntimeError, match='cannot create scroll-only uinput device'):
        gestures.ScrollEmitter(device_factory=fail_factory)


def test_v14_preflight_does_not_require_event_node_read_access():
    scroll_emitter = Mock()
    scroll_emitter.__enter__ = Mock(return_value=scroll_emitter)
    scroll_emitter.__exit__ = Mock(return_value=None)
    scroll_emitter.device.capabilities.side_effect = PermissionError('write-only runtime')
    pinch_emitter = Mock()
    pinch_emitter.__enter__ = Mock(return_value=pinch_emitter)
    pinch_emitter.__exit__ = Mock(return_value=None)
    pinch_emitter.device.capabilities.side_effect = PermissionError('write-only runtime')

    assert gestures.check_uinput(
        emitter_factory=Mock(return_value=scroll_emitter),
        pinch_emitter_factory=Mock(return_value=pinch_emitter),
    )
    scroll_emitter.device.capabilities.assert_not_called()
    pinch_emitter.device.capabilities.assert_not_called()
