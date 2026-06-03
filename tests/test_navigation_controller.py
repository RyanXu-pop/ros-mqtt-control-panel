import math
import os
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.controllers.navigation_controller import NavigationController


@pytest.fixture
def mock_mqtt():
    return MagicMock()


@pytest.fixture
def nav_ctrl(mock_mqtt):
    return NavigationController(mqtt_agent=mock_mqtt)


def test_send_goal(nav_ctrl, mock_mqtt):
    affine_M_inv = np.eye(3)

    rx, ry, yaw = nav_ctrl.send_goal(10.0, 10.0, affine_M_inv, robot_x=0.0, robot_y=0.0)

    assert rx == 10.0
    assert ry == 10.0
    assert yaw == pytest.approx(45.0)

    mock_mqtt.publish.assert_called_once()
    args, kwargs = mock_mqtt.publish.call_args
    assert args[0] == "goal"
    assert args[1]["x"] == 10.0
    assert args[1]["y"] == 10.0
    assert args[1]["yaw"] == pytest.approx(math.pi / 4)


def test_publish_initial_pose(nav_ctrl, mock_mqtt):
    result = nav_ctrl.publish_initial_pose(1.5, -2.5, math.pi / 2)

    assert result is True
    mock_mqtt.publish.assert_called_once()
    args, kwargs = mock_mqtt.publish.call_args
    assert args[0] == "initial_pose"
    assert args[1]["x"] == 1.5
    assert args[1]["y"] == -2.5
    assert args[1]["yaw"] == pytest.approx(math.pi / 2)
    assert args[1]["angle"] == pytest.approx(90.0)


def test_set_initial_pose(nav_ctrl, mock_mqtt):
    affine_M_inv = np.eye(3)
    result = nav_ctrl.set_initial_pose(5.0, 5.0, math.pi, affine_M_inv)

    assert result is True
    mock_mqtt.publish.assert_called_once()
    args, kwargs = mock_mqtt.publish.call_args
    assert args[0] == "initial_pose"
    assert args[1]["x"] == 5.0
    assert args[1]["y"] == 5.0
    assert args[1]["yaw"] == pytest.approx(math.pi)
    assert args[1]["angle"] == pytest.approx(180.0)
