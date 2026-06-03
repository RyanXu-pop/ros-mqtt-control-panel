import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.controllers.inspection_plan_manager import InspectionPlanManager
from src.controllers.patrol_controller import PatrolController
from src.core.models import RobotPose


def _store(**overrides):
    base = {
        "chassis_running": True,
        "mqtt_broker_connected": True,
        "navigation_running": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_patrol_direct_mode_publishes_low_speed_cmd_vel(tmp_path, qapp):
    manager = InspectionPlanManager(str(tmp_path / "plans.json"))
    manager.update_current_plan(mode="direct", arrival_threshold=0.2)
    manager.add_waypoint(1.0, 0.0, 0.0, name="P1")
    patrol = PatrolController(manager, _store())
    commands = []
    patrol.command_velocity_requested.connect(lambda linear, angular: commands.append((linear, angular)))
    patrol.on_robot_pose(RobotPose(x=0.0, y=0.0, yaw=0.0, angle=0.0))

    assert patrol.start() is True

    assert patrol.running is True
    assert commands
    assert 0.0 < commands[-1][0] <= 0.15
    assert abs(commands[-1][1]) <= 0.45


def test_patrol_direct_mode_stops_on_stale_pose(tmp_path, qapp):
    manager = InspectionPlanManager(str(tmp_path / "plans.json"))
    manager.update_current_plan(mode="direct")
    manager.add_waypoint(1.0, 0.0, 0.0, name="P1")
    patrol = PatrolController(manager, _store())
    commands = []
    patrol.command_velocity_requested.connect(lambda linear, angular: commands.append((linear, angular)))
    patrol.on_robot_pose(RobotPose(x=0.0, y=0.0, yaw=0.0, angle=0.0))

    patrol.start()
    patrol._latest_pose_at = time.monotonic() - 3.0
    patrol._tick()

    assert patrol.paused is True
    assert commands[-1] == (0.0, 0.0)


def test_patrol_nav2_mode_requests_dependencies_when_navigation_is_down(tmp_path, qapp):
    manager = InspectionPlanManager(str(tmp_path / "plans.json"))
    manager.update_current_plan(mode="nav2")
    manager.add_waypoint(1.0, 0.0, 0.0, name="P1")
    patrol = PatrolController(manager, _store(navigation_running=False))
    requested = []
    patrol.ensure_navigation_requested.connect(lambda: requested.append(True))

    assert patrol.start() is True

    assert requested == [True]
    assert patrol.running is False
