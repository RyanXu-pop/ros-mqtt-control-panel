"""
TeleopController 单元测试
验证键盘遥控核心逻辑：速度计算 + 零速保护
"""
import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# 需要在 import Qt 之前 mock QApplication
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from PySide6.QtCore import Qt
from src.controllers.teleop_controller import TeleopController, ZERO_GRACE_COUNT


@pytest.fixture
def mock_mqtt():
    mqtt = MagicMock()
    mqtt.is_connected = True
    mqtt.client = MagicMock()
    return mqtt


@pytest.fixture
def ctrl(mock_mqtt):
    return TeleopController(mqtt_agent=mock_mqtt)


class FakeKeyEvent:
    """模拟 QKeyEvent"""
    def __init__(self, key, auto_repeat=False):
        self._key = key
        self._auto_repeat = auto_repeat

    def key(self):
        return self._key

    def isAutoRepeat(self):
        return self._auto_repeat


def test_press_w_sets_forward_speed(ctrl):
    """按下 W 应该设置正向线速度"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_W))
    assert ctrl.target_linear == ctrl.max_linear_speed
    assert ctrl.target_angular == 0.0


def test_press_s_sets_backward_speed(ctrl):
    """按下 S 应该设置反向线速度"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_S))
    assert ctrl.target_linear == -ctrl.max_linear_speed


def test_press_a_sets_left_turn(ctrl):
    """按下 A 应该设置正向角速度（左转）"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_A))
    assert ctrl.target_angular == ctrl.max_angular_speed


def test_press_d_sets_right_turn(ctrl):
    """按下 D 应设置负向角速度（右转）"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_D))
    assert ctrl.target_angular == -ctrl.max_angular_speed


def test_release_all_keys_triggers_zero_grace(ctrl):
    """松开所有按键应启动零速保护帧"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_W))
    ctrl.handle_key_release(FakeKeyEvent(Qt.Key_W))
    assert ctrl.target_linear == 0.0
    assert ctrl._zero_grace_remaining == ZERO_GRACE_COUNT


def test_zero_grace_countdown(ctrl, mock_mqtt):
    """零速保护帧倒计时正常工作"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_W))
    ctrl.handle_key_release(FakeKeyEvent(Qt.Key_W))

    # 每次 _publish_cmd_vel 应该消耗一帧
    for i in range(ZERO_GRACE_COUNT):
        ctrl._publish_cmd_vel()
        assert mock_mqtt.client.publish.called

    # 保护帧耗尽后不再发送
    mock_mqtt.client.publish.reset_mock()
    ctrl._publish_cmd_vel()
    mock_mqtt.client.publish.assert_not_called()


def test_idle_no_publish(ctrl, mock_mqtt):
    """初始空闲状态下不应发送任何消息"""
    ctrl._publish_cmd_vel()
    mock_mqtt.client.publish.assert_not_called()


def test_auto_repeat_ignored(ctrl):
    """自动重复的按键事件应被忽略"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_W))
    assert len(ctrl.pressed_keys) == 1
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_W, auto_repeat=True))
    assert len(ctrl.pressed_keys) == 1


def test_combined_keys(ctrl):
    """同时按下 W + A 应该产生前进+左转"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_W))
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_A))
    assert ctrl.target_linear == ctrl.max_linear_speed
    assert ctrl.target_angular == ctrl.max_angular_speed


def test_opposite_keys_cancel(ctrl):
    """同时按下 W + S 应该抵消线速度"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_W))
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_S))
    assert ctrl.target_linear == 0.0


def test_non_teleop_key_not_intercepted(ctrl):
    """非遥控按键不应被拦截"""
    assert ctrl.handle_key_press(FakeKeyEvent(Qt.Key_X)) is False


def test_space_emergency_stop_clears_keys_and_sends_zero(ctrl, mock_mqtt):
    """Space 应立即清空运动按键并发布零速指令"""
    ctrl.handle_key_press(FakeKeyEvent(Qt.Key_W))
    assert ctrl.target_linear == ctrl.max_linear_speed

    assert ctrl.handle_key_press(FakeKeyEvent(Qt.Key_Space)) is True

    assert ctrl.pressed_keys == set()
    assert ctrl.target_linear == 0.0
    assert ctrl.target_angular == 0.0
    args, _kwargs = mock_mqtt.client.publish.call_args
    payload = json.loads(args[1])
    assert payload["linear"]["x"] == 0.0
    assert payload["angular"]["z"] == 0.0
