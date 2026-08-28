from pathlib import Path
from unittest.mock import patch

import pytest

import magic_mouse_gestures as gestures


def make_touch(touch_id: int, x: int, y: int) -> gestures.Touch:
    return gestures.Touch(
        id=touch_id,
        x=x,
        y=y,
        major=10,
        minor=10,
        size=10,
        orientation=0,
        state=1,
    )


def make_state(finger_count: int) -> gestures.GestureState:
    return gestures.GestureState(
        start_x=1000,
        start_y=1000,
        start_time=1.0,
        finger_count=finger_count,
    )


def test_one_finger_horizontal_motion_is_reserved_for_native_scroll():
    state = make_state(finger_count=1)

    with patch.object(gestures.time, "monotonic", return_value=1.2):
        result = gestures.detect_gesture(
            [make_touch(0, x=1400, y=1000)],
            state,
        )

    assert result is None
    assert state.start_x is None


def test_short_two_finger_horizontal_motion_does_not_navigate():
    state = make_state(finger_count=2)

    with patch.object(gestures.time, "monotonic", return_value=1.2):
        result = gestures.detect_gesture(
            [
                make_touch(0, x=1150, y=1000),
                make_touch(1, x=1150, y=1000),
            ],
            state,
        )

    assert result is None


def test_deliberate_two_finger_horizontal_swipe_navigates():
    state = make_state(finger_count=2)

    with patch.object(gestures.time, "monotonic", return_value=1.2):
        result = gestures.detect_gesture(
            [
                make_touch(0, x=1400, y=1000),
                make_touch(1, x=1400, y=1000),
            ],
            state,
        )

    assert result == "swipe_right"


def test_v17_sysfs_bitmap_detects_middle_click_capability():
    assert gestures.capability_bitmap_has_code("70001 0 0 0 0", gestures.BTN_MIDDLE_CODE)
    assert not gestures.capability_bitmap_has_code("30001 0 0 0 0", gestures.BTN_MIDDLE_CODE)


@pytest.mark.parametrize("product", sorted(gestures.PRODUCT_IDS))
def test_v17_physical_middle_click_check_accepts_supported_products(
    tmp_path: Path,
    product: str,
):
    physical = tmp_path / "event30" / "device"
    physical.mkdir(parents=True)
    (physical / "id").mkdir()
    (physical / "id" / "vendor").write_text("004c\n", encoding="ascii")
    (physical / "id" / "product").write_text(f"{product}\n", encoding="ascii")
    (physical / "capabilities").mkdir()
    (physical / "capabilities" / "key").write_text("70001 0 0 0 0\n", encoding="ascii")

    assert gestures.physical_middle_click_available(str(tmp_path))


def test_v41_hidraw_match_uses_exact_supported_bluetooth_ids():
    assert gestures.supported_hid_uevent(
        "HID_ID=0005:0000004C:00000269\nHID_NAME=Magic Mouse\n"
    )
    assert gestures.supported_hid_uevent(
        "HID_ID=0005:0000004C:00000323\nHID_NAME=Magic Mouse\n"
    )
    assert not gestures.supported_hid_uevent(
        "HID_ID=0003:0000004C:00000323\nHID_NAME=Magic Mouse\n"
    )
    assert not gestures.supported_hid_uevent(
        "HID_ID=0005:0000004C:00000324\nHID_NAME=Magic Mouse 0323\n"
    )
    assert not gestures.supported_hid_uevent("HID_NAME=Magic Mouse 004c 0323\n")


def test_v41_middle_click_check_rejects_unknown_product(tmp_path: Path):
    physical = tmp_path / "event30" / "device"
    physical.mkdir(parents=True)
    (physical / "id").mkdir()
    (physical / "id" / "vendor").write_text("004c\n", encoding="ascii")
    (physical / "id" / "product").write_text("0324\n", encoding="ascii")
    (physical / "capabilities").mkdir()
    (physical / "capabilities" / "key").write_text(
        "70001 0 0 0 0\n",
        encoding="ascii",
    )

    assert not gestures.physical_middle_click_available(str(tmp_path))


def test_v17_install_enables_middle_click_before_reprobe():
    repo_root = Path(__file__).resolve().parents[1]
    install_script = (repo_root / "install.sh").read_text(encoding="utf-8")
    module_config = (
        repo_root / "modprobe" / "99-magic-mouse-wayland-gestures.conf"
    ).read_text(encoding="utf-8")

    enable_index = install_script.index(
        "write_parameter emulate_3button 1"
    )
    disconnect_index = install_script.index('bluetoothctl disconnect')
    verify_index = install_script.index('--check-middle-click')
    reconnect_index = install_script.index('bluetoothctl connect')

    assert enable_index < disconnect_index
    assert reconnect_index < verify_index
    assert "emulate_3button=1" in module_config


def test_v25_v26_preflight_precedes_transactional_kernel_change():
    repo_root = Path(__file__).resolve().parents[1]
    install_script = (repo_root / "install.sh").read_text(encoding="utf-8")

    rules_index = install_script.index("udevadm control --reload-rules")
    preflight_index = install_script.index("--check-uinput")
    kernel_change_index = install_script.index("write_parameter scroll_acceleration 0")

    assert rules_index < preflight_index < kernel_change_index
    assert "trap 'rollback $?' ERR" in install_script
    assert 'PROJECT="magic-mouse-wayland-gestures"' in install_script
    assert 'MODPROBE_FILE="/etc/modprobe.d/99-$PROJECT.conf"' in install_script


def test_v27_v28_never_targets_generic_mouse_or_world_writable_hidraw():
    repo_root = Path(__file__).resolve().parents[1]
    install_script = (repo_root / "install.sh").read_text(encoding="utf-8")
    rules = (
        repo_root / "udev" / "70-magic-mouse-wayland-gestures.rules"
    ).read_text(encoding="utf-8")

    assert "Magic Mouse" in install_script
    assert "devices Connected" not in install_script
    assert 'MODE="0666"' not in rules
    assert 'TAG+="uaccess"' in rules


def test_v39_uaccess_rule_precedes_systemd_seat_acl_processing():
    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "udev" / "70-magic-mouse-wayland-gestures.rules"
    rules = rules_path.read_text(encoding="utf-8")
    magic_mouse_rules = [
        line
        for line in rules.splitlines()
        if any(
            f'KERNELS=="0005:004C:{product.upper()}.*"' in line
            for product in gestures.PRODUCT_IDS
        )
    ]
    install_script = (repo_root / "install.sh").read_text(encoding="utf-8")
    uninstall_script = (repo_root / "uninstall.sh").read_text(encoding="utf-8")

    assert int(rules_path.name.split("-", 1)[0]) < 73
    assert len(magic_mouse_rules) == len(gestures.PRODUCT_IDS)
    assert all('TAG+="uaccess"' in rule for rule in magic_mouse_rules)
    assert all('RUN{builtin}+="uaccess"' not in rule for rule in magic_mouse_rules)
    assert 'UDEV_FILE="/etc/udev/rules.d/70-$PROJECT.rules"' in install_script
    assert 'LEGACY_UDEV_FILE="/etc/udev/rules.d/99-$PROJECT.rules"' in install_script
    assert 'sudo rm -f "$LEGACY_UDEV_FILE"' in install_script
    assert '"$LEGACY_UDEV_FILE"' in uninstall_script


def test_v40_service_starts_only_with_the_graphical_session():
    repo_root = Path(__file__).resolve().parents[1]
    service = (
        repo_root / "systemd" / "magic-mouse-wayland-gestures.service"
    ).read_text(encoding="utf-8")
    install_script = (repo_root / "install.sh").read_text(encoding="utf-8")

    assert "PartOf=graphical-session.target" in service
    assert "After=graphical-session-pre.target" in service
    assert "WantedBy=graphical-session.target" in service
    assert "WantedBy=default.target" not in service
    assert 'systemctl --user reenable "$SERVICE_NAME"' in install_script


def test_v29_uninstall_is_nonrecursive_and_removes_owned_ydotool_service():
    repo_root = Path(__file__).resolve().parents[1]
    uninstall_script = (repo_root / "uninstall.sh").read_text(encoding="utf-8")

    assert "rm -rf" not in uninstall_script
    assert 'YDOTOOL_SERVICE_NAME="$PROJECT-ydotool.service"' in uninstall_script
    assert "ydotool.service.d" not in uninstall_script
    assert "emulate_scroll_wheel" in uninstall_script
    assert "emulate_3button" in uninstall_script


def test_v29_navigation_uses_a_dedicated_keyboard_only_ydotool_socket():
    repo_root = Path(__file__).resolve().parents[1]
    main_service = (
        repo_root / "systemd" / "magic-mouse-wayland-gestures.service"
    ).read_text(encoding="utf-8")
    ydotool_service = (
        repo_root / "systemd" / "magic-mouse-wayland-gestures-ydotool.service"
    ).read_text(encoding="utf-8")

    assert "Wants=magic-mouse-wayland-gestures-ydotool.service" in main_service
    assert "Environment=YDOTOOL_SOCKET=%t/magic-mouse-wayland-gestures.sock" in main_service
    assert "--mouse-off" in ydotool_service
    assert "--socket-path=%t/magic-mouse-wayland-gestures.sock" in ydotool_service
    assert "StartLimitIntervalSec=0" in ydotool_service
    assert "ydotool.service.d" not in main_service + ydotool_service


def test_v32_services_apply_hardening_without_private_devices():
    repo_root = Path(__file__).resolve().parents[1]
    services = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (repo_root / "systemd").glob("*.service")
    )

    for setting in (
        "NoNewPrivileges=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "MemoryDenyWriteExecute=true",
    ):
        assert setting in services
    assert "PrivateDevices=true" not in services
    # Ubuntu's unprivileged user manager cannot apply this setting and exits
    # with 218/CAPABILITIES before either process starts.
    assert "ProtectKernelModules=true" not in services
