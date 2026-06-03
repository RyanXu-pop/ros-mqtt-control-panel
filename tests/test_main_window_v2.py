import math
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.models import RobotPose
from src.ui_v2.main_window import MyMainWindow


def _make_dummy_for_pose_update():
    store = SimpleNamespace(mapping_running=True, update_robot_pose=MagicMock())
    dummy = SimpleNamespace(
        store=store,
        _frame_transforms={},
        _mapping_pose_log_counter=0,
    )
    dummy._is_finite_values = MyMainWindow._is_finite_values
    dummy._invert_transform = MyMainWindow._invert_transform
    dummy._compose_transforms = MyMainWindow._compose_transforms
    dummy._lookup_transform = lambda parent, child: MyMainWindow._lookup_transform(dummy, parent, child)
    dummy._resolve_transform_chain = lambda parent, child, max_depth=6: MyMainWindow._resolve_transform_chain(dummy, parent, child, max_depth)
    dummy._resolve_mapping_pose_from_tf = lambda: MyMainWindow._resolve_mapping_pose_from_tf(dummy)
    return dummy


def test_mapping_pose_prefers_direct_map_to_base_tf():
    dummy = _make_dummy_for_pose_update()
    dummy._frame_transforms[("map", "base_footprint")] = {"x": 1.5, "y": -0.4, "yaw": 0.3}
    dummy._refresh_mapping_pose = lambda: MyMainWindow._refresh_mapping_pose(dummy)

    MyMainWindow._on_odom_data(dummy, RobotPose(x=9.0, y=9.0, yaw=1.2, angle=68.75493541569878, source="odom"))

    updated = dummy.store.update_robot_pose.call_args.args[0]
    assert updated.x == 1.5
    assert updated.y == -0.4
    assert updated.yaw == 0.3
    assert updated.source == "tf_map_base"


def test_mapping_pose_composes_map_odom_with_odom_base():
    dummy = _make_dummy_for_pose_update()
    dummy._frame_transforms[("map", "odom")] = {"x": 2.0, "y": 1.0, "yaw": math.pi / 2}
    dummy._frame_transforms[("odom", "base_footprint")] = {"x": 1.0, "y": 0.0, "yaw": 0.1}
    dummy._refresh_mapping_pose = lambda: MyMainWindow._refresh_mapping_pose(dummy)

    MyMainWindow._on_odom_data(dummy, RobotPose(x=0.0, y=0.0, yaw=0.0, angle=0.0, source="odom"))

    updated = dummy.store.update_robot_pose.call_args.args[0]
    assert updated.x == pytest.approx(2.0)
    assert updated.y == pytest.approx(2.0)
    assert updated.yaw == pytest.approx(math.pi / 2 + 0.1)
    assert updated.source == "tf_map_odom_base"


def test_mapping_pose_does_not_fall_back_to_odom_when_tf_missing():
    dummy = _make_dummy_for_pose_update()
    dummy._refresh_mapping_pose = lambda: MyMainWindow._refresh_mapping_pose(dummy)
    odom_pose = RobotPose(x=1.2, y=-0.5, yaw=0.25, angle=14.32394487827058, source="odom")

    MyMainWindow._on_odom_data(dummy, odom_pose)

    dummy.store.update_robot_pose.assert_not_called()


def test_mapping_scan_skips_when_map_tf_is_missing():
    dummy = SimpleNamespace(
        store=SimpleNamespace(mapping_running=True),
        _show_mapping_scan_overlay=True,
        _last_scan_received_at=time.monotonic(),
        _mapping_scan_log_counter=0,
        _last_mapping_scan_status="",
        _resolve_scan_pose_in_map=lambda _frame_id: None,
        _log_mapping_scan=MagicMock(),
        ui=SimpleNamespace(map_view=SimpleNamespace(update_scan=MagicMock(), clear_scan=MagicMock())),
    )

    MyMainWindow._on_store_scan_changed(dummy, {"frame_id": "laser", "ranges": [1.0]})

    dummy.ui.map_view.clear_scan.assert_called_once()
    dummy.ui.map_view.update_scan.assert_not_called()


def test_mapping_scan_renders_current_frame_with_map_tf():
    scan_transform = {"x": 1.1, "y": 1.95, "yaw": 0.35}
    dummy = SimpleNamespace(
        store=SimpleNamespace(mapping_running=True, navigation_running=False),
        _show_mapping_scan_overlay=True,
        _last_scan_received_at=time.monotonic(),
        _mapping_scan_log_counter=0,
        _last_mapping_scan_status="",
        _should_render_scan_overlay=lambda: True,
        _resolve_scan_pose_in_map=lambda _frame_id: scan_transform,
        _log_mapping_scan=MagicMock(),
        ui=SimpleNamespace(map_view=SimpleNamespace(update_scan=MagicMock(), clear_scan=MagicMock())),
    )
    scan_dict = {"frame_id": "laser", "angle_min": 0.0, "angle_increment": 0.1, "ranges": [1.0]}

    MyMainWindow._on_store_scan_changed(dummy, scan_dict)

    args = dummy.ui.map_view.update_scan.call_args.args
    assert args[0] == scan_dict
    assert args[1] == pytest.approx(scan_transform["x"])
    assert args[2] == pytest.approx(scan_transform["y"])
    assert args[3] == pytest.approx(scan_transform["yaw"])
    dummy.ui.map_view.clear_scan.assert_not_called()


def test_navigation_scan_renders_current_frame_with_map_tf():
    scan_transform = {"x": 1.1, "y": 1.95, "yaw": 0.35}
    dummy = SimpleNamespace(
        store=SimpleNamespace(mapping_running=False, navigation_running=True),
        _should_render_scan_overlay=lambda: True,
        _resolve_scan_pose_in_map=lambda _frame_id: scan_transform,
        _log_scan_transform_diagnostic=MagicMock(),
        ui=SimpleNamespace(map_view=SimpleNamespace(update_scan=MagicMock(), clear_scan=MagicMock())),
    )
    scan_dict = {"frame_id": "laser", "angle_min": 0.0, "angle_increment": 0.1, "ranges": [1.0]}

    MyMainWindow._on_store_scan_changed(dummy, scan_dict)

    args = dummy.ui.map_view.update_scan.call_args.args
    assert args[0] == scan_dict
    assert args[1] == pytest.approx(scan_transform["x"])
    assert args[2] == pytest.approx(scan_transform["y"])
    assert args[3] == pytest.approx(scan_transform["yaw"])
    dummy.ui.map_view.clear_scan.assert_not_called()


def test_scan_is_not_rendered_when_mapping_and_navigation_are_stopped():
    dummy = SimpleNamespace(
        store=SimpleNamespace(mapping_running=False, navigation_running=False),
        _should_render_scan_overlay=lambda: False,
        _resolve_scan_pose_in_map=MagicMock(),
        ui=SimpleNamespace(map_view=SimpleNamespace(update_scan=MagicMock(), clear_scan=MagicMock())),
    )

    MyMainWindow._on_store_scan_changed(dummy, {"frame_id": "laser", "ranges": [1.0]})

    dummy.ui.map_view.clear_scan.assert_called_once()
    dummy.ui.map_view.update_scan.assert_not_called()
    dummy._resolve_scan_pose_in_map.assert_not_called()


def test_scan_transform_chain_composes_map_base_laser():
    store = SimpleNamespace(mapping_running=True, current_pose=None)
    dummy = SimpleNamespace(
        store=store,
        _frame_transforms={
            ("map", "base_link"): {"x": 1.0, "y": 2.0, "yaw": math.pi / 2},
            ("base_link", "laser"): {"x": 0.2, "y": 0.0, "yaw": 0.1},
        },
    )
    dummy._invert_transform = MyMainWindow._invert_transform
    dummy._compose_transforms = MyMainWindow._compose_transforms
    dummy._resolve_transform_chain = lambda parent, child, max_depth=6: MyMainWindow._resolve_transform_chain(dummy, parent, child, max_depth)

    transform = MyMainWindow._resolve_scan_pose_in_map(dummy, "laser")

    assert transform["x"] == pytest.approx(1.0)
    assert transform["y"] == pytest.approx(2.2)
    assert transform["yaw"] == pytest.approx(math.pi / 2 + 0.1)


def test_mapping_scan_falls_back_to_map_base_when_laser_static_tf_missing():
    store = SimpleNamespace(mapping_running=True, current_pose=None)
    dummy = SimpleNamespace(
        store=store,
        _frame_transforms={
            ("map", "base_link"): {"x": 3.0, "y": -1.0, "yaw": 0.4},
        },
    )
    dummy._invert_transform = MyMainWindow._invert_transform
    dummy._compose_transforms = MyMainWindow._compose_transforms
    dummy._resolve_transform_chain = lambda parent, child, max_depth=6: MyMainWindow._resolve_transform_chain(dummy, parent, child, max_depth)
    dummy._lookup_transform_chain_for_scan = lambda parent, child: MyMainWindow._lookup_transform_chain_for_scan(dummy, parent, child)

    transform = MyMainWindow._resolve_scan_pose_in_map(dummy, "laser")

    assert transform["x"] == pytest.approx(3.0)
    assert transform["y"] == pytest.approx(-1.0)
    assert transform["yaw"] == pytest.approx(0.4)


def test_mapping_state_change_clears_local_map_and_dynamic_layers():
    store = SimpleNamespace(update_path=MagicMock(), update_scan=MagicMock())
    dummy = SimpleNamespace(
        store=store,
        ui=SimpleNamespace(map_view=SimpleNamespace(clear_map=MagicMock(), clear_path=MagicMock(), clear_scan=MagicMock())),
        _map_source="local",
        _live_map_received=True,
        _cleared_for_live_map=False,
        _mapping_map_log_counter=7,
        _mapping_scan_log_counter=9,
        _last_mapping_scan_status="rendered",
    )

    MyMainWindow._on_mapping_state_changed(dummy, True)

    dummy.ui.map_view.clear_map.assert_called_once()
    dummy.ui.map_view.clear_path.assert_called_once()
    dummy.ui.map_view.clear_scan.assert_called_once()
    store.update_path.assert_called_once_with([])
    store.update_scan.assert_called_once_with({})
    assert dummy._live_map_received is False
    assert dummy._cleared_for_live_map is True
    assert dummy._mapping_map_log_counter == 0


def test_plan_path_still_renders_while_mapping():
    dummy = SimpleNamespace(
        store=SimpleNamespace(mapping_running=True),
        ui=SimpleNamespace(map_view=SimpleNamespace(update_path=MagicMock(), clear_path=MagicMock())),
    )
    path = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]

    MyMainWindow._on_store_path_changed(dummy, path)

    dummy.ui.map_view.update_path.assert_called_once_with(path)
    dummy.ui.map_view.clear_path.assert_not_called()


def test_live_map_switches_mapping_view_to_live_source():
    map_meta = object()
    store = SimpleNamespace(mapping_running=True, update_map=MagicMock())
    dummy = SimpleNamespace(
        store=store,
        _map_source="local",
        _live_map_received=False,
        _cleared_for_live_map=True,
        _mapping_map_log_counter=0,
        _last_live_map_received_at=None,
    )

    MyMainWindow._on_live_map_data(dummy, map_meta)

    store.update_map.assert_called_once_with(map_meta)
    assert dummy._map_source == "live_mqtt"
    assert dummy._live_map_received is True
    assert dummy._cleared_for_live_map is False


def test_live_map_is_accepted_while_waiting_for_first_live_frame():
    map_meta = object()
    store = SimpleNamespace(mapping_running=False, update_map=MagicMock())
    dummy = SimpleNamespace(
        store=store,
        _map_source="local",
        _live_map_received=False,
        _cleared_for_live_map=True,
        _mapping_map_log_counter=0,
        _last_live_map_received_at=None,
    )

    MyMainWindow._on_live_map_data(dummy, map_meta)

    store.update_map.assert_called_once_with(map_meta)
    assert dummy._map_source == "live_mqtt"
    assert dummy._live_map_received is True
    assert dummy._cleared_for_live_map is False


def test_amcl_pose_is_ignored_in_mapping_mode():
    dummy = SimpleNamespace(
        store=SimpleNamespace(mapping_running=True, update_robot_pose=MagicMock()),
        _is_finite_values=MyMainWindow._is_finite_values,
    )
    pose = RobotPose(x=2.0, y=3.0, yaw=0.2, angle=11.459155902616466, source="amcl")

    MyMainWindow._on_pose_data(dummy, pose)

    dummy.store.update_robot_pose.assert_not_called()


def test_amcl_pose_updates_robot_pose_when_not_mapping():
    dummy = SimpleNamespace(
        store=SimpleNamespace(mapping_running=False, update_robot_pose=MagicMock()),
        _is_finite_values=MyMainWindow._is_finite_values,
    )
    pose = RobotPose(x=2.0, y=3.0, yaw=0.2, angle=11.459155902616466, source="amcl")

    MyMainWindow._on_pose_data(dummy, pose)

    dummy.store.update_robot_pose.assert_called_once_with(pose)
