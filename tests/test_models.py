import math

import numpy as np
import pytest

from src.core.models import MapMetadata, RobotPose


def test_robot_pose_from_dict_standard():
    data = {"x": 1.0, "y": 2.0, "z": 0.5, "yaw": math.pi / 2, "source": "amcl"}
    pose = RobotPose.from_dict(data)

    assert pose.x == 1.0
    assert pose.y == 2.0
    assert pose.z == 0.5
    assert pose.yaw == pytest.approx(math.pi / 2)
    assert pose.angle == pytest.approx(90.0)
    assert pose.source == "amcl"


def test_robot_pose_from_dict_missing_values():
    data = {"x": 5.0}
    pose = RobotPose.from_dict(data, default_source="odom")

    assert pose.x == 5.0
    assert pose.y == 0.0
    assert pose.yaw == 0.0
    assert pose.angle == 0.0
    assert pose.source == "odom"


def test_robot_pose_with_angle_instead_of_yaw():
    data = {"angle": 180.0}
    pose = RobotPose.from_dict(data)

    assert pose.angle == 180.0
    assert pose.yaw == pytest.approx(math.pi)


def test_robot_pose_with_large_yaw_infers_angle():
    data = {"yaw": 180.0}
    pose = RobotPose.from_dict(data)

    assert pose.angle == 180.0
    assert pose.yaw == pytest.approx(math.pi)


def test_robot_pose_duplicate_radian_angle_uses_degrees():
    data = {"yaw": math.pi / 2, "angle": math.pi / 2}
    pose = RobotPose.from_dict(data)

    assert pose.yaw == pytest.approx(math.pi / 2)
    assert pose.angle == pytest.approx(90.0)


def test_robot_pose_invalid_input():
    pose = RobotPose.from_dict(None)
    assert pose.x == 0.0
    assert pose.y == 0.0
    assert pose.yaw == 0.0


def test_robot_pose_non_finite_values_fall_back_to_zero():
    pose = RobotPose.from_dict({"x": "nan", "y": float("inf"), "yaw": float("-inf"), "angle": "nan"})

    assert pose.x == 0.0
    assert pose.y == 0.0
    assert pose.yaw == 0.0
    assert pose.angle == 0.0


def test_map_metadata_from_dict():
    data = {
        "resolution": 0.02,
        "origin_x": -10.0,
        "origin_yaw": math.pi / 4,
        "width": 100,
        "height": 200,
        "data": np.zeros((200, 100)),
    }
    meta = MapMetadata.from_dict(data)

    assert meta.resolution == 0.02
    assert meta.origin_x == -10.0
    assert meta.origin_y == 0.0
    assert meta.origin_yaw == pytest.approx(math.pi / 4)
    assert meta.width == 100
    assert meta.height == 200
    assert meta.encoding == "image"
    assert isinstance(meta.data, np.ndarray)
